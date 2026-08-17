/// <reference lib="webworker" />

import { certifyReplaySafety } from "./certifyReplaySafety";

type SafetyWorkerInput = Parameters<typeof certifyReplaySafety>[0];

self.onmessage = (event: MessageEvent<SafetyWorkerInput>) => {
  try {
    self.postMessage({ report: certifyReplaySafety(event.data) });
  } catch (error) {
    self.postMessage({
      error: error instanceof Error ? error.message : "Unknown frontend safety error",
    });
  }
};

export {};
