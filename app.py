#!/usr/bin/env python3

import os
import arrow
import logging
import json
import time
import asyncio
import requests
import re
import collections
from urllib.parse import urljoin, urlencode
import base64

from flask import Flask, Response, request, abort, redirect, jsonify, render_template

is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")
if is_gunicorn:
    from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics as PrometheusMetrics
else:
    from prometheus_flask_exporter import PrometheusMetrics

from prometheus_client import Counter, Gauge

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(__name__)

app = Flask(__name__)

metrics = PrometheusMetrics(app)

PLAYLIST_URL = os.getenv('PLAYLIST_URL')
if not PLAYLIST_URL:
    print('No PLAYLIST_URL=')
    exit(1)

PROXY_BASE = os.getenv('PROXY_BASE')

_playlist_data = None
def get_playlist_data():
    global _playlist_data
    if _playlist_data:
        return _playlist_data
    
    r = requests.get(PLAYLIST_URL)
    playlists = []
    tmp = []
    for line in r.text.splitlines():
        if line and line.startswith('#EXTM3U'):
            continue
        if line:
            tmp.append(line)
        else:
            playlists.append(tmp)
            tmp = []
    playlists.append(tmp)

    _playlist_data = playlists
    return playlists


def parse_kv_pairs(line):
    pattern = r'(\S+?)=(?:"([^"]*)"|(\S+))'
    matches = re.findall(pattern, line)
    if not matches:
        return {}

    parsed_data = {key: (val1 if val1 else val2) for key, val1, val2 in matches}

    return parsed_data

def get_playlist_metadata():
    groups = collections.defaultdict(list)
    playlists = get_playlist_data()
    meta = []
    for plines in playlists:
        met = {}
        kv = parse_kv_pairs(plines[0].split(' ',1)[1])
        met.update(kv)
        for l in plines[1:]:
            if l.startswith('#EXTVLCOPT:'):
                kv2 = parse_kv_pairs(l[len('#EXTVLCOPT:'):])
                if kv2:
                    met.update(kv2)
            elif l.startswith('http'):
                met['raw_url'] = l

        met['m3u8'] = build_m3u8_url(met)
        met['m3u8_player'] = build_m3u8_player_url(met)
        meta.append(met)

        if 'group-title' in met:
            groups[met['group-title']].append(met)
    


    return meta, groups

def build_m3u8_url(met):
    data = []
    if 'http-referrer' in met:
        data.append('Referer=' + met.get('http-referrer'))
    if 'http-referer' in met:
        data.append('Referer=' + met.get('http-referer'))
    if 'http-origin' in met:
        data.append('Origin=' + met.get('http-origin'))
    if 'http-user-agent' in met:
        data.append('User-Agent=' + met.get('http-user-agent'))
    
    return urljoin(PROXY_BASE, '/playlist.m3u8?' + urlencode({
        'url': met['raw_url'],
        'data': base64.b64encode('|'.join(data).encode()).decode()
    }))

def build_m3u8_player_url(met):
    return '/play?' + urlencode({
        'tvg-id': met['tvg-id']
    })


@app.route('/')
def index():
    meta, groups = get_playlist_metadata()
    return render_template('index.html', meta=meta, groups=groups)

@app.route('/play')
def play():
    meta, groups = get_playlist_metadata()
    tvgId = request.args.get('tvg-id')
    detail = None
    for m in meta:
        if m['tvg-id'] == tvgId:
            detail = m
            break
    if not detail:
        return 'could not find id'
    
    return render_template('play.html', playlist=detail)

@app.route('/healthz')
def healthz_route():
    return 'ok'