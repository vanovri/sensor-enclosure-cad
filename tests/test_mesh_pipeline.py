"""Independent orientation/distance properties and the real mesh-report CLI."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mesh_checks import Mesh, ray_hits, read_stl, topology, volume_and_bbox


def test_winding_changes_signed_volume_without_changing_closed_topology():
    points=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],dtype=float)
    faces=np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]],dtype=int)
    forward,reverse=Mesh(points,faces),Mesh(points,faces[:,::-1])
    assert topology(forward)['watertight'] is True
    assert topology(reverse)['watertight'] is True
    assert volume_and_bbox(forward)['signed_volume_mm3']==pytest.approx(0.167)
    assert volume_and_bbox(reverse)['signed_volume_mm3']==pytest.approx(-0.167)
    assert topology(Mesh(points,faces[:-1]))['watertight'] is False


def test_ray_distance_is_independent_of_direction_magnitude():
    mesh=read_stl(ROOT/'stl/base.stl')
    origin=(100.0,0.0,10.0)
    unit=ray_hits(mesh,origin,(-1.0,0.0,0.0))
    scaled=ray_hits(mesh,origin,(-7.0,0.0,0.0))
    assert len(unit)>=2
    assert scaled==pytest.approx(unit)
    assert ray_hits(mesh,origin,(-1.0,0.0,0.0),limit=unit[0]/2)==[]


def test_real_mesh_cli_reconstructs_parts_and_writes_passing_report(tmp_path):
    output=tmp_path/'mesh report.json'
    result=subprocess.run([sys.executable,str(ROOT/'mesh_checks.py'),'--spec',str(ROOT/'specs/sensor_gateway.json'),
                            '--stl-dir',str(ROOT/'stl'),'--out',str(output)],
                           capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stderr
    report=json.loads(output.read_text(encoding='utf-8'))
    assert report['passed'] is True
    assert set(report['parts'])=={'base','lid','assembly'}
    assert all(part['passed'] for part in report['parts'].values())
    assert json.loads(result.stdout)['all'] is True


def test_mesh_cli_records_all_missing_parts_and_returns_failure(tmp_path):
    output=tmp_path/'failed.json'
    result=subprocess.run([sys.executable,str(ROOT/'mesh_checks.py'),'--spec',str(ROOT/'specs/sensor_gateway.json'),
                            '--stl-dir',str(tmp_path/'absent'),'--out',str(output)],
                           capture_output=True,text=True,timeout=30)
    assert result.returncode==1
    report=json.loads(output.read_text(encoding='utf-8'))
    assert report['passed'] is False
    assert all('missing ' in part['error'] for part in report['parts'].values())
