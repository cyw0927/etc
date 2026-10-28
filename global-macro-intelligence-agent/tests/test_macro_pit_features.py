from datetime import date,datetime,timedelta,timezone
import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from gmia.models.registry import CompleteCaseLogit
spec=importlib.util.spec_from_file_location('macro_pit',Path(__file__).resolve().parents[1]/'src'/'gmia'/'features'/'macro_pit.py')
mod=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=mod
spec.loader.exec_module(mod)
UTC=timezone.utc

def revision(value, release, ingested, evidence='exact_verified', day=date(2020,1,1)):
    return mod.MacroRevision('CPI',day,value,release,ingested,'https://example.org/release','a'*64,evidence)

def test_release_ingestion_revision_time_and_no_lookahead():
    t=datetime(2020,2,1,tzinfo=UTC)
    first=revision(1,t,t+timedelta(hours=1)); second=revision(2,t+timedelta(days=1),t+timedelta(days=1,hours=2))
    assert np.isnan(mod.features_at([first],t,['CPI'])['CPI_pit'])
    assert mod.features_at([first,second],t+timedelta(days=1,hours=1),['CPI'])['CPI_pit']==1
    assert mod.features_at([first,second],t+timedelta(days=1,hours=2),['CPI'])['CPI_pit']==2
    assert np.isnan(mod.features_at([revision(3,t,t,'unknown')],t,['CPI'])['CPI_pit'])
    with pytest.raises(ValueError): mod.features_at([first],datetime(2020,2,1),['CPI'])

def test_conflicting_same_release_and_bad_hash_fail():
    t=datetime(2020,2,1,tzinfo=UTC)
    with pytest.raises(ValueError): mod.features_at([revision(1,t,t),revision(2,t,t)],t,['CPI'])
    bad=mod.MacroRevision('CPI',date(2020,1,1),1,t,t,'https://example.org','bad','exact_verified')
    with pytest.raises(ValueError): mod.features_at([bad],t,['CPI'])

def test_synthetic_integration_existing_logit_model():
    t=datetime(2020,2,1,tzinfo=UTC)
    records=[revision(float(i),t+timedelta(days=i),t+timedelta(days=i),day=(t+timedelta(days=i)).date()) for i in range(70)]
    decisions=[t+timedelta(days=i) for i in range(70)]
    x=mod.feature_matrix(records,decisions,['CPI']); y=pd.Series([i%2 for i in range(70)],index=x.index)
    model=CompleteCaseLogit('research_only',['CPI_pit']).fit(x,y)
    probs=model.predict_proba(x)
    assert len(probs)==70 and np.isfinite(probs).all() and model.pipe_ is not None
