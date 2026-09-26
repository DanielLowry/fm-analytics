"""Shared, fail-closed FM UI-thread selection for Frida agents.

The old agents sampled ``QueryPerformanceCounter`` and required its busiest
caller to beat the runner-up by five times. That identified FM's UI thread in
the original captures, but it is an indirect signal and becomes ambiguous as
FM's foreground/background state and worker load change.

The agents already execute native calls at a Windows message-pump boundary.
This selector also uses those calls as the primary identity signal: one thread
observed calling the message pump is the UI thread. Multiple pump threads stay
ambiguous unless the established QPC dominance rule independently selects one
of them. If no pump call is observed, the original QPC rule remains the
fallback. No ambiguous thread is guessed.
"""

from __future__ import annotations

import json


RESTING_POINT_EXPORTS = ("GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA")
THREAD_SAMPLE_EXPORT = "QueryPerformanceCounter"
THREAD_SAMPLE_MILLISECONDS = 1000


UI_THREAD_SELECTOR_SOURCE = r"""
function availableRestingPoints() {
  const points = [];
  const seen = {};
  for (const name of config.restingPointExports) {
    const address = Module.findGlobalExportByName(name);
    if (address === null || seen[address.toString()]) continue;
    seen[address.toString()] = true;
    points.push({name, address});
  }
  return points;
}
function dominantQpcThread(sample) {
  const ranked = Object.entries(sample).sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0) return null;
  if (ranked.length > 1 && ranked[0][1] < ranked[1][1] * 5) return null;
  return Number(ranked[0][0]);
}
function busiestPumpForThread(points, pumpSample, thread) {
  const calls = pumpSample[String(thread)] || {};
  const ranked = Object.entries(calls).sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0) return null;
  return points.find(point => point.name === ranked[0][0]) || null;
}
function selectUiThread(run) {
  const timing = Module.findGlobalExportByName(config.threadSampleExport);
  if (timing === null) throw new Error(config.threadSampleExport + ' export not found');
  const restingPoints = availableRestingPoints();
  const qpcSample = {};
  const pumpSample = {};
  const samplers = [Interceptor.attach(timing, {onEnter() {
    const id = String(Process.getCurrentThreadId());
    qpcSample[id] = (qpcSample[id] || 0) + 1;
  }})];
  for (const point of restingPoints) {
    samplers.push(Interceptor.attach(point.address, {onEnter() {
      const id = String(Process.getCurrentThreadId());
      if (!(id in pumpSample)) pumpSample[id] = {};
      pumpSample[id][point.name] = (pumpSample[id][point.name] || 0) + 1;
    }}));
  }
  setTimeout(() => {
    for (const sampler of samplers) sampler.detach();
    const pumpThreads = Object.keys(pumpSample);
    const qpcThread = dominantQpcThread(qpcSample);
    let thread = null;
    let hook = null;
    let selection = null;
    if (pumpThreads.length === 1) {
      thread = Number(pumpThreads[0]);
      hook = busiestPumpForThread(restingPoints, pumpSample, thread);
      selection = 'unique-message-pump-thread';
    } else if (pumpThreads.length > 1 && qpcThread !== null && String(qpcThread) in pumpSample) {
      thread = qpcThread;
      hook = busiestPumpForThread(restingPoints, pumpSample, thread);
      selection = 'dominant-qpc-message-pump-thread';
    } else if (pumpThreads.length === 0 && qpcThread !== null) {
      thread = qpcThread;
      hook = {name: config.threadSampleExport, address: timing};
      selection = 'dominant-qpc-fallback';
    }
    if (thread === null || hook === null) {
      send({kind: 'error', error: 'no unambiguous FM UI thread was found',
        qpcSample, pumpSample});
      return;
    }
    send({kind: 'thread', thread, sample: qpcSample, pumpSample,
      hook: hook.name, restingPoint: hook.name !== config.threadSampleExport,
      selection});
    let state = 'armed';
    const runner = Interceptor.attach(hook.address, {onEnter() {
      if (state !== 'armed' || Process.getCurrentThreadId() !== thread) return;
      state = 'running';
      try {
        run();
      } catch (error) {
        state = 'failed';
        send({kind: 'error', error: String(error)});
        return;
      }
      state = 'done';
      setTimeout(() => { runner.detach(); send({kind: 'finished'}); }, 0);
    }});
  }, config.threadSampleMs);
}
"""


def thread_selection_config() -> dict[str, object]:
    """The shared config fields required by ``UI_THREAD_SELECTOR_SOURCE``."""
    return {
        "threadSampleMs": THREAD_SAMPLE_MILLISECONDS,
        "restingPointExports": list(RESTING_POINT_EXPORTS),
        "threadSampleExport": THREAD_SAMPLE_EXPORT,
    }


def probe_agent_source(module_base: str) -> str:
    """A passive selector probe: hooks exports but invokes no FM function."""
    config = {"moduleBase": module_base, **thread_selection_config()}
    source = r"""
'use strict';
const config = __CONFIG__;
const fm = Process.getModuleByName('fm.exe');
if (!fm.base.equals(ptr(config.moduleBase))) {
  send({kind: 'error', error: 'FM module base differs from preflight'});
  throw new Error('FM module base differs from preflight');
}
__UI_THREAD_SELECTOR__
send({kind: 'ready', moduleBase: fm.base.toString()});
selectUiThread(() => {});
"""
    return (
        source.replace("__CONFIG__", json.dumps(config))
        .replace("__UI_THREAD_SELECTOR__", UI_THREAD_SELECTOR_SOURCE)
    )
