"""Pure geometric invariants only. No mock remote responses or fake datasets."""
from apps.api.app.routing import haversine, evenly_sample
from apps.api.app.models import Point

def test_haversine_identity():
    p=Point(lat=0,lon=0)
    assert haversine(p,p)==0

def test_route_sampling_respects_endpoints():
    # Runtime constructed test coordinates are an algorithm invariant, NOT an operational dataset.
    coords=[[0.0,0.0],[0.01,0.01]]
    points=evenly_sample(coords,max_samples=3)
    assert points[0]==Point(lat=0.0,lon=0.0)
    assert points[-1]==Point(lat=0.01,lon=0.01)
