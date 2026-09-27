"""Shared, fail-closed FM UI-thread selection for Frida agents.

The old agents sampled ``QueryPerformanceCounter`` and required its busiest
caller to beat the runner-up by five times. That identified FM's UI thread in
the original captures, but it is an indirect signal and becomes ambiguous as
FM's foreground/background state and worker load change.

The agents execute native calls only at a Windows message-pump boundary, and
this selector uses those calls as the primary identity signal: one thread
observed calling the message pump is the UI thread. Multiple pump threads stay
ambiguous unless the established QPC dominance rule independently selects one
of them. No ambiguous thread is guessed.

Corrected 27 September 2026: when no pump call was observed, this selector
used to fall back to running the call inside the dominant thread's next
``QueryPerformanceCounter`` call. That is the exact timing
``docs/property-discovery-playbook.md`` names as the likeliest cause of saves
that write and then fail to load, and it came back with the selector's
introduction on 26 September, the same evening saves broke again. It now
refuses instead. ``QueryPerformanceCounter`` is still *sampled*, as the
tie-break between several pump threads, but a call never runs there.
"""

from __future__ import annotations

import json


RESTING_POINT_EXPORTS = ("GetMessageW", "GetMessageA", "PeekMessageW", "PeekMessageA")
THREAD_SAMPLE_EXPORT = "QueryPerformanceCounter"
THREAD_SAMPLE_MILLISECONDS = 1000


# The decision alone, with no Frida globals, so tests can run it directly.
UI_THREAD_CHOICE_SOURCE = r"""
function dominantQpcThread(sample) {
  const ranked = Object.entries(sample).sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0) return null;
  if (ranked.length > 1 && ranked[0][1] < ranked[1][1] * 5) return null;
  return Number(ranked[0][0]);
}
function busiestPumpName(pumpSample, thread) {
  const ranked = Object.entries(pumpSample[String(thread)] || {}).sort((a, b) => b[1] - a[1]);
  return ranked.length === 0 ? null : ranked[0][0];
}
// Returns {thread, pump, selection}, or null when the UI thread is ambiguous.
// `pump` is always a message-pump export name: there is no timing-call fallback.
function chooseUiThread(qpcSample, pumpSample) {
  const pumpThreads = Object.keys(pumpSample);
  let thread = null;
  let selection = null;
  if (pumpThreads.length === 1) {
    thread = Number(pumpThreads[0]);
    selection = 'unique-message-pump-thread';
  } else if (pumpThreads.length > 1) {
    const qpcThread = dominantQpcThread(qpcSample);
    if (qpcThread !== null && String(qpcThread) in pumpSample) {
      thread = qpcThread;
      selection = 'dominant-qpc-message-pump-thread';
    }
  }
  if (thread === null) return null;
  const pump = busiestPumpName(pumpSample, thread);
  return pump === null ? null : {thread, pump, selection};
}
"""


UI_THREAD_SELECTOR_SOURCE = UI_THREAD_CHOICE_SOURCE + r"""
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
    const choice = chooseUiThread(qpcSample, pumpSample);
    const hook = choice === null ? null : restingPoints.find(point => point.name === choice.pump);
    if (!hook) {
      send({kind: 'error', error: 'no unambiguous FM UI thread was found',
        qpcSample, pumpSample});
      return;
    }
    const thread = choice.thread;
    send({kind: 'thread', thread, sample: qpcSample, pumpSample,
      hook: hook.name, restingPoint: true, selection: choice.selection});
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
