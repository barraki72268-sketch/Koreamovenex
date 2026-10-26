"""Inspection-day semantics are independent of the calendar date in the source."""
import numpy as np
import pandas as pd


def measurement_timestamp(dates,times):
    dates=pd.to_datetime(dates,errors='raise').dt.normalize()
    strings=times.astype(str).str.strip()
    numeric=pd.to_numeric(strings,errors='coerce')
    fraction=numeric.ge(0)&numeric.lt(1)
    extracted=strings.str.extract(r'(\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)',expand=False)
    extracted=extracted.where(extracted.str.count(':').ne(1),extracted+':00')
    delta=pd.to_timedelta(extracted,errors='coerce')
    delta.loc[fraction]=pd.to_timedelta(numeric.loc[fraction],unit='D')
    return dates+delta


def crack_inspection_days(frame,start_hour=6):
    if not 0<=float(start_hour)<24:raise ValueError('검사일 시작 시각은 0~23시입니다.')
    g=frame.copy()
    g['calendar_date']=pd.to_datetime(g.c0).dt.strftime('%Y-%m-%d')
    g['timestamp']=measurement_timestamp(g.c0,g.c1)
    if g.timestamp.isna().any():raise ValueError('크랙 MASTER를 정하려면 모든 측정행의 시간 형식을 확인해야 합니다.')
    g['c0']=(g.timestamp-pd.Timedelta(hours=float(start_hour))).dt.strftime('%Y-%m-%d')
    g=g.sort_values(['timestamp','source_sheet','source_row'],kind='stable').reset_index(drop=True)
    # A partial export that starts after midnight must not invent a prior-day master.
    daytime=g.calendar_date.eq(g.c0)
    first=g[daytime].groupby('c0',sort=False).head(1).index
    master=np.zeros(len(g),bool);master[first]=True
    return g,master
