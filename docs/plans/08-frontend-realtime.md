# GABI Frontend Real-Time Updates Design

**Date:** 2026-02-12  
**Scope:** Vanilla JS frontend real-time capabilities for discovery/ingest pipeline  
**Target:** `/home/fgamajr/dev/gabi-kimi/web/src/`  
**API Base:** `http://localhost:5100` (proxied via Vite from `localhost:3000`)

---

## Executive Summary

This document designs a real-time update system for GABI's vanilla JS frontend, enabling live progress tracking during source discovery and document ingestion. The solution prioritizes **Server-Sent Events (SSE)** as the primary transport, with **intelligent polling fallback** and **comprehensive offline support**.

### Current Pain Points
1. Manual refresh required to see discovery progress
2. No visibility into long-running operations
3. Discovered links lost on page refresh
4. Failed operations require manual retry

### Goals
1. ✅ Real-time progress updates during discovery/ingest
2. ✅ Live status transitions (pending → running → completed)
3. ✅ Notifications when sources complete
4. ✅ Persist discovered links in localStorage
5. ✅ Automatic retry with exponential backoff

---

## 1. Technology Evaluation

### 1.1 Comparison Matrix

| Criteria | SSE | WebSockets | Long Polling | Short Polling |
|----------|-----|------------|--------------|---------------|
| **Direction** | Server→Client only | Bidirectional | Server→Client | Client-initiated |
| **Browser Support** | 98%+ | 97%+ | Universal | Universal |
| **Reconnection** | Built-in (EventSource) | Manual | Automatic | Automatic |
| **HTTP Compatible** | ✅ Yes | ❌ Upgrade needed | ✅ Yes | ✅ Yes |
| **Firewall Friendly** | ✅ Yes | ⚠️ Sometimes blocked | ✅ Yes | ✅ Yes |
| **Binary Data** | ❌ Base64 | ✅ Native | ❌ Base64 | ❌ Base64 |
| **Overhead** | Low | Very Low | Medium | High |
| **Implementation** | Simple | Moderate | Simple | Simple |
| **GABI Fit** | ✅ Excellent | ⚠️ Overkill | ✅ Good | ⚠️ Inefficient |

### 1.2 Recommendation: Hybrid SSE + Polling

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONNECTION STRATEGY                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Primary:    SSE (EventSource)                                 │
│   ├── Real-time progress events                                 │
│   ├── Status change notifications                               │
│   └── Automatic reconnection with exponential backoff           │
│                                                                  │
│   Fallback:   Smart Polling                                     │
│   ├── SSE unavailable or error → switch to polling              │
│   ├── Adaptive interval based on activity                       │
│   │   ├── Active operations: 2s                                 │
│   │   ├── Idle with recent activity: 10s                        │
│   │   └── Idle: 30s                                             │
│   └── Exponential backoff on errors                             │
│                                                                  │
│   Offline:    Queue + Sync                                      │
│   ├── Actions queued in localStorage                            │
│   ├── Background sync when connection restored                  │
│   └── Conflict resolution for server/local state                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 Why Not SignalR/WebSockets?

For GABI's use case:
- **Overkill**: Unidirectional flow (server→client) sufficient
- **Infrastructure**: Requires sticky sessions or Redis backplane
- **Complexity**: Adds 100KB+ to bundle, requires SignalR client
- **Benefits don't justify cost** for simple progress updates

---

## 2. Architecture Design

### 2.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          BROWSER                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │   UI Layer   │  │  State Mgr   │  │     Sync Engine          │  │
│  │              │  │              │  │                          │  │
│  │ SourceList   │◄─┤  Store       │◄─┤  ActionQueue             │  │
│  │ SourceDetail │  │  (Proxy)     │  │  ConflictResolver        │  │
│  │ ToastMgr     │  │              │  │  LocalStorageAdapter     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                 │                        │                │
│         └─────────────────┴────────────────────────┘                │
│                           │                                         │
│  ┌────────────────────────▼────────────────────────┐               │
│  │              Connection Manager                  │               │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────┐  │               │
│  │  │  SSE Client │  │Poll Adapter  │  │Heartbeat│  │               │
│  │  │  (Primary)  │  │(Fallback)    │  │Monitor │  │               │
│  │  └──────┬──────┘  └──────┬───────┘  └───┬────┘  │               │
│  │         └─────────────────┴──────────────┘       │               │
│  │                           │                       │               │
│  └───────────────────────────┼───────────────────────┘               │
│                              │                                      │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │    GABI.API         │
                    │  (ASP.NET Core)     │
                    │  Port: 5100         │
                    └─────────────────────┘
```

### 2.2 Module Structure

```
web/src/
├── core/
│   ├── event-bus.js          # Central event system
│   ├── connection-manager.js # SSE + polling abstraction
│   ├── retry-policy.js       # Exponential backoff logic
│   └── state-manager.js      # Proxy-based reactive state
│
├── sync/
│   ├── action-queue.js       # Offline action queue
│   ├── conflict-resolver.js  # Server vs local resolution
│   ├── local-storage.js      # Persist discovered links
│   └── sync-engine.js        # Background synchronization
│
├── api/
│   ├── api.js                # HTTP client (existing)
│   ├── sse-client.js         # EventSource wrapper
│   └── polling-client.js     # Smart polling fallback
│
├── ui/
│   ├── toast-manager.js      # Notification system
│   ├── progress-bar.js       # Progress indicator component
│   └── status-badge.js       # Live status component
│
└── utils/
    ├── debounce.js
    ├── throttle.js
    └── uuid.js
```

---

## 3. Core Implementation

### 3.1 Event Bus (Pub/Sub)

```javascript
// core/event-bus.js
/**
 * Central event bus for decoupled communication
 * Enables: RealTime → UI updates without direct coupling
 */
export class EventBus {
  constructor() {
    this.events = new Map();
  }

  on(event, callback, options = {}) {
    if (!this.events.has(event)) {
      this.events.set(event, new Set());
    }
    
    const handler = { callback, once: options.once || false };
    this.events.get(event).add(handler);
    
    // Return unsubscribe function
    return () => this.events.get(event)?.delete(handler);
  }

  once(event, callback) {
    return this.on(event, callback, { once: true });
  }

  emit(event, data) {
    const handlers = this.events.get(event);
    if (!handlers) return;

    handlers.forEach(handler => {
      try {
        handler.callback(data);
      } catch (err) {
        console.error(`Event handler error for ${event}:`, err);
      }
      if (handler.once) {
        handlers.delete(handler);
      }
    });
  }

  off(event, callback) {
    if (!callback) {
      this.events.delete(event);
      return;
    }
    const handlers = this.events.get(event);
    if (handlers) {
      for (const handler of handlers) {
        if (handler.callback === callback) {
          handlers.delete(handler);
          break;
        }
      }
    }
  }
}

// Singleton instance
export const eventBus = new EventBus();

// Event types
export const Events = {
  // Connection
  CONNECTED: 'connection:connected',
  DISCONNECTED: 'connection:disconnected',
  RECONNECTING: 'connection:reconnecting',
  
  // Source operations
  SOURCE_REFRESH_START: 'source:refresh:start',
  SOURCE_PROGRESS: 'source:progress',
  SOURCE_COMPLETED: 'source:completed',
  SOURCE_FAILED: 'source:failed',
  
  // Sync
  SYNC_PENDING: 'sync:pending',
  SYNC_COMPLETED: 'sync:completed',
  CONFLICT_DETECTED: 'sync:conflict',
  
  // Notifications
  NOTIFY: 'notify',
};
```

### 3.2 Connection Manager (SSE + Fallback)

```javascript
// core/connection-manager.js
import { eventBus, Events } from './event-bus.js';
import { RetryPolicy } from './retry-policy.js';

/**
 * Manages real-time connection with SSE primary and polling fallback
 * Handles: Connection lifecycle, reconnection, transport negotiation
 */
export class ConnectionManager {
  constructor(options = {}) {
    this.options = {
      sseEndpoint: '/api/v1/events',
      pollEndpoint: '/api/v1/sources/status',
      heartbeatInterval: 30000,
      connectionTimeout: 10000,
      ...options,
    };

    this.state = 'disconnected'; // disconnected, connecting, connected, reconnecting
    this.transport = null; // 'sse' | 'polling'
    this.eventSource = null;
    this.pollInterval = null;
    this.heartbeatTimer = null;
    this.retryPolicy = new RetryPolicy({
      maxRetries: 10,
      baseDelay: 1000,
      maxDelay: 30000,
    });
    
    // Activity tracking for adaptive polling
    this.lastActivity = Date.now();
    this.activeOperations = new Set();
  }

  async connect() {
    if (this.state === 'connected' || this.state === 'connecting') {
      return;
    }

    this.state = 'connecting';

    // Try SSE first
    if (this.isSSESupported()) {
      try {
        await this.connectSSE();
        return;
      } catch (err) {
        console.warn('SSE connection failed, falling back to polling:', err);
      }
    }

    // Fallback to polling
    await this.connectPolling();
  }

  disconnect() {
    this.cleanup();
    this.state = 'disconnected';
    eventBus.emit(Events.DISCONNECTED);
  }

  isSSESupported() {
    return typeof EventSource !== 'undefined';
  }

  async connectSSE() {
    return new Promise((resolve, reject) => {
      const url = `${this.options.sseEndpoint}?clientId=${this.getClientId()}`;
      
      this.eventSource = new EventSource(url);
      
      const timeout = setTimeout(() => {
        this.eventSource.close();
        reject(new Error('SSE connection timeout'));
      }, this.options.connectionTimeout);

      this.eventSource.onopen = () => {
        clearTimeout(timeout);
        this.state = 'connected';
        this.transport = 'sse';
        this.retryPolicy.reset();
        this.startHeartbeat();
        eventBus.emit(Events.CONNECTED, { transport: 'sse' });
        resolve();
      };

      this.eventSource.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.eventSource.onerror = (err) => {
        clearTimeout(timeout);
        this.handleTransportError(err);
        reject(err);
      };

      // Listen for specific event types
      this.eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        eventBus.emit(Events.SOURCE_PROGRESS, data);
        this.trackActivity(data.sourceId);
      });

      this.eventSource.addEventListener('completed', (e) => {
        const data = JSON.parse(e.data);
        eventBus.emit(Events.SOURCE_COMPLETED, data);
        this.activeOperations.delete(data.sourceId);
      });
    });
  }

  async connectPolling() {
    this.transport = 'polling';
    this.state = 'connected';
    eventBus.emit(Events.CONNECTED, { transport: 'polling' });
    
    this.schedulePoll();
  }

  schedulePoll() {
    const interval = this.calculatePollInterval();
    
    this.pollInterval = setTimeout(async () => {
      if (this.state !== 'connected') return;
      
      try {
        await this.poll();
        this.retryPolicy.reset();
      } catch (err) {
        this.handleTransportError(err);
      } finally {
        if (this.state === 'connected') {
          this.schedulePoll();
        }
      }
    }, interval);
  }

  calculatePollInterval() {
    // Adaptive polling based on activity
    const idleTime = Date.now() - this.lastActivity;
    const hasActiveOps = this.activeOperations.size > 0;

    if (hasActiveOps) return 2000;           // Active: 2s
    if (idleTime < 60000) return 10000;      // Recent activity: 10s
    return 30000;                            // Idle: 30s
  }

  async poll() {
    const sourceIds = Array.from(this.activeOperations);
    const params = sourceIds.length > 0 
      ? `?sources=${sourceIds.join(',')}` 
      : '';
    
    const response = await fetch(`${this.options.pollEndpoint}${params}`);
    if (!response.ok) throw new Error(`Poll failed: ${response.status}`);
    
    const updates = await response.json();
    updates.forEach(update => this.handleMessage(JSON.stringify(update)));
  }

  handleMessage(data) {
    try {
      const message = typeof data === 'string' ? JSON.parse(data) : data;
      
      // Route to appropriate event
      switch (message.type) {
        case 'progress':
          eventBus.emit(Events.SOURCE_PROGRESS, message.payload);
          break;
        case 'completed':
          eventBus.emit(Events.SOURCE_COMPLETED, message.payload);
          break;
        case 'failed':
          eventBus.emit(Events.SOURCE_FAILED, message.payload);
          break;
        case 'heartbeat':
          // Connection alive
          break;
        default:
          eventBus.emit(message.type, message.payload);
      }
    } catch (err) {
      console.error('Failed to handle message:', err);
    }
  }

  handleTransportError(err) {
    console.error('Transport error:', err);
    this.cleanup();
    
    const attempt = this.retryPolicy.nextAttempt();
    
    if (attempt.shouldRetry) {
      this.state = 'reconnecting';
      eventBus.emit(Events.RECONNECTING, { 
        attempt: attempt.attemptNumber,
        delay: attempt.delay 
      });
      
      setTimeout(() => this.connect(), attempt.delay);
    } else {
      this.state = 'disconnected';
      eventBus.emit(Events.DISCONNECTED, { error: err });
    }
  }

  startHeartbeat() {
    this.heartbeatTimer = setInterval(() => {
      if (this.eventSource?.readyState === EventSource.OPEN) {
        // SSE has built-in heartbeat via connection
      }
    }, this.options.heartbeatInterval);
  }

  trackActivity(sourceId) {
    this.lastActivity = Date.now();
    if (sourceId) {
      this.activeOperations.add(sourceId);
    }
  }

  cleanup() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    if (this.pollInterval) {
      clearTimeout(this.pollInterval);
      this.pollInterval = null;
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  getClientId() {
    let id = localStorage.getItem('gabi-client-id');
    if (!id) {
      id = `client-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      localStorage.setItem('gabi-client-id', id);
    }
    return id;
  }
}
```

### 3.3 Retry Policy (Exponential Backoff)

```javascript
// core/retry-policy.js

/**
 * Exponential backoff retry policy with jitter
 * Prevents thundering herd and handles transient failures
 */
export class RetryPolicy {
  constructor(options = {}) {
    this.maxRetries = options.maxRetries || 5;
    this.baseDelay = options.baseDelay || 1000;
    this.maxDelay = options.maxDelay || 30000;
    this.multiplier = options.multiplier || 2;
    this.jitter = options.jitter !== false; // Add randomness
    
    this.attemptNumber = 0;
  }

  nextAttempt() {
    this.attemptNumber++;
    
    if (this.attemptNumber > this.maxRetries) {
      return { shouldRetry: false, attemptNumber: this.attemptNumber };
    }

    // Exponential delay: base * 2^(attempt-1)
    let delay = this.baseDelay * Math.pow(this.multiplier, this.attemptNumber - 1);
    delay = Math.min(delay, this.maxDelay);

    // Add jitter (±25%) to prevent thundering herd
    if (this.jitter) {
      const jitterFactor = 0.75 + Math.random() * 0.5;
      delay = Math.floor(delay * jitterFactor);
    }

    return {
      shouldRetry: true,
      attemptNumber: this.attemptNumber,
      delay,
    };
  }

  reset() {
    this.attemptNumber = 0;
  }

  get isExhausted() {
    return this.attemptNumber >= this.maxRetries;
  }
}
```

### 3.4 State Manager (Reactive)

```javascript
// core/state-manager.js
import { eventBus, Events } from './event-bus.js';

/**
 * Proxy-based reactive state manager
 * Enables: Optimistic UI updates with automatic notification
 */
export function createStateManager(initialState = {}) {
  const listeners = new Map();
  const state = { ...initialState };

  const proxy = new Proxy(state, {
    set(target, property, value) {
      const oldValue = target[property];
      
      if (oldValue === value) return true;
      
      target[property] = value;
      
      // Notify property-specific listeners
      const propListeners = listeners.get(property);
      if (propListeners) {
        propListeners.forEach(cb => cb(value, oldValue));
      }
      
      // Notify wildcard listeners
      const wildcards = listeners.get('*');
      if (wildcards) {
        wildcards.forEach(cb => cb(property, value, oldValue));
      }
      
      return true;
    },
    
    get(target, property) {
      return target[property];
    },
  });

  return {
    state: proxy,
    
    subscribe(property, callback) {
      if (!listeners.has(property)) {
        listeners.set(property, new Set());
      }
      listeners.get(property).add(callback);
      
      // Return unsubscribe
      return () => listeners.get(property)?.delete(callback);
    },
    
    unsubscribe(property, callback) {
      listeners.get(property)?.delete(callback);
    },
    
    // Batch multiple updates
    batch(updates) {
      const previous = {};
      
      // Capture previous values
      Object.keys(updates).forEach(key => {
        previous[key] = state[key];
      });
      
      // Apply updates (triggers notifications)
      Object.entries(updates).forEach(([key, value]) => {
        state[key] = value;
      });
      
      return previous;
    },
  };
}

/**
 * Source-specific state slice with optimistic updates
 */
export function createSourceState(sourceId) {
  const manager = createStateManager({
    id: sourceId,
    status: 'idle', // idle, pending, running, completed, failed
    progress: 0,
    linksDiscovered: 0,
    links: [],
    error: null,
    lastUpdated: null,
    optimistic: false,
  });

  return {
    ...manager,
    
    // Optimistic update helpers
    setOptimistic(status) {
      manager.batch({
        status,
        optimistic: true,
        lastUpdated: Date.now(),
      });
    },
    
    confirmUpdate(updates) {
      manager.batch({
        ...updates,
        optimistic: false,
        lastUpdated: Date.now(),
      });
    },
    
    rollback() {
      // Revert optimistic update - requires snapshot
      manager.batch({
        optimistic: false,
      });
    },
  };
}
```

---

## 4. Offline Support

### 4.1 Action Queue

```javascript
// sync/action-queue.js
import { eventBus, Events } from '../core/event-bus.js';

const QUEUE_KEY = 'gabi-action-queue';
const SYNC_STATUS_KEY = 'gabi-sync-status';

/**
 * Queues actions for offline execution
 * Persists to localStorage, processes on reconnection
 */
export class ActionQueue {
  constructor() {
    this.queue = this.loadQueue();
    this.processing = false;
    
    // Listen for online status
    window.addEventListener('online', () => this.processQueue());
  }

  enqueue(action) {
    const item = {
      id: `action-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      type: action.type,
      payload: action.payload,
      timestamp: Date.now(),
      retries: 0,
      maxRetries: 3,
    };

    this.queue.push(item);
    this.saveQueue();
    
    eventBus.emit(Events.SYNC_PENDING, { item, queueLength: this.queue.length });
    
    // Try to process immediately if online
    if (navigator.onLine) {
      this.processQueue();
    }
    
    return item.id;
  }

  async processQueue() {
    if (this.processing || this.queue.length === 0 || !navigator.onLine) {
      return;
    }

    this.processing = true;
    
    const processed = [];
    const failed = [];

    for (const item of [...this.queue]) {
      try {
        await this.executeAction(item);
        processed.push(item.id);
      } catch (err) {
        item.retries++;
        item.lastError = err.message;
        
        if (item.retries >= item.maxRetries) {
          failed.push(item);
          processed.push(item.id); // Remove from queue
        }
      }
    }

    // Update queue
    this.queue = this.queue.filter(item => !processed.includes(item.id));
    this.saveQueue();
    
    this.processing = false;
    
    eventBus.emit(Events.SYNC_COMPLETED, { 
      processed: processed.length, 
      failed: failed.length,
      remaining: this.queue.length 
    });

    // Retry failed items later
    if (failed.length > 0) {
      setTimeout(() => this.processQueue(), 60000);
    }
  }

  async executeAction(item) {
    switch (item.type) {
      case 'REFRESH_SOURCE':
        const { api } = await import('../api/api.js');
        return await api.refreshSource(item.payload.sourceId);
        
      default:
        throw new Error(`Unknown action type: ${item.type}`);
    }
  }

  loadQueue() {
    try {
      const stored = localStorage.getItem(QUEUE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  }

  saveQueue() {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(this.queue));
  }

  clear() {
    this.queue = [];
    localStorage.removeItem(QUEUE_KEY);
  }

  get pendingCount() {
    return this.queue.length;
  }
}

export const actionQueue = new ActionQueue();
```

### 4.2 Local Storage Adapter

```javascript
// sync/local-storage.js

const STORAGE_KEY = 'gabi-source-cache';
const VERSION = 1;

/**
 * Persistent storage for discovered links
 * Enables: Survive page refresh, offline viewing
 */
export class LocalStorageAdapter {
  constructor() {
    this.cache = this.load();
    this.maxAge = 24 * 60 * 60 * 1000; // 24 hours
  }

  load() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (!stored) return new Map();
      
      const data = JSON.parse(stored);
      if (data.version !== VERSION) {
        this.migrate(data);
      }
      
      return new Map(Object.entries(data.sources || {}));
    } catch (err) {
      console.error('Failed to load cache:', err);
      return new Map();
    }
  }

  save() {
    const data = {
      version: VERSION,
      lastSync: Date.now(),
      sources: Object.fromEntries(this.cache),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  }

  get(sourceId) {
    const entry = this.cache.get(sourceId);
    if (!entry) return null;
    
    // Check expiry
    if (Date.now() - entry.timestamp > this.maxAge) {
      this.cache.delete(sourceId);
      this.save();
      return null;
    }
    
    return entry.data;
  }

  set(sourceId, data) {
    this.cache.set(sourceId, {
      timestamp: Date.now(),
      data,
    });
    this.save();
  }

  getLinks(sourceId) {
    const entry = this.get(sourceId);
    return entry?.links || [];
  }

  setLinks(sourceId, links) {
    const existing = this.get(sourceId) || {};
    this.set(sourceId, { ...existing, links });
  }

  clear(sourceId) {
    if (sourceId) {
      this.cache.delete(sourceId);
    } else {
      this.cache.clear();
    }
    this.save();
  }

  migrate(oldData) {
    // Handle future migrations
    return { version: VERSION, sources: {} };
  }

  // Estimate storage usage
  get usage() {
    const data = localStorage.getItem(STORAGE_KEY);
    return data ? new Blob([data]).size : 0;
  }
}

export const localCache = new LocalStorageAdapter();
```

### 4.3 Conflict Resolver

```javascript
// sync/conflict-resolver.js

/**
 * Resolves conflicts between server and local state
 * Strategy: Server wins for status, Merge for links
 */
export class ConflictResolver {
  constructor(strategy = 'server-wins') {
    this.strategy = strategy;
  }

  resolve(local, server) {
    switch (this.strategy) {
      case 'server-wins':
        return this.serverWins(local, server);
      case 'merge':
        return this.merge(local, server);
      case 'last-write-wins':
        return this.lastWriteWins(local, server);
      default:
        return server;
    }
  }

  // Server state takes precedence for status/progress
  // Local links are merged with server links (deduplicated)
  serverWins(local, server) {
    const mergedLinks = this.mergeLinks(
      local?.links || [],
      server?.links || []
    );

    return {
      ...server,
      links: mergedLinks,
      conflictResolved: true,
      conflictStrategy: 'server-wins',
    };
  }

  // Deep merge of all fields
  merge(local, server) {
    return {
      ...local,
      ...server,
      links: this.mergeLinks(local?.links || [], server?.links || []),
      conflictResolved: true,
      conflictStrategy: 'merge',
    };
  }

  // Compare timestamps
  lastWriteWins(local, server) {
    const localTime = local?.lastUpdated || 0;
    const serverTime = server?.lastUpdated || 0;

    return localTime > serverTime ? local : server;
  }

  mergeLinks(localLinks, serverLinks) {
    const urlMap = new Map();
    
    // Add local links first
    localLinks.forEach(link => {
      urlMap.set(link.url, { ...link, source: 'local' });
    });
    
    // Merge server links (overwrite if newer)
    serverLinks.forEach(link => {
      const existing = urlMap.get(link.url);
      if (!existing || new Date(link.discoveredAt) > new Date(existing.discoveredAt)) {
        urlMap.set(link.url, { ...link, source: 'server' });
      }
    });
    
    return Array.from(urlMap.values())
      .sort((a, b) => new Date(b.discoveredAt) - new Date(a.discoveredAt));
  }
}

export const conflictResolver = new ConflictResolver('server-wins');
```

---

## 5. UI Components

### 5.1 Toast Manager (Notifications)

```javascript
// ui/toast-manager.js
import { eventBus, Events } from '../core/event-bus.js';

/**
 * Non-intrusive notification system
 */
export class ToastManager {
  constructor(container) {
    this.container = container || this.createContainer();
    this.toasts = new Map();
    this.defaultDuration = 5000;
    
    this.setupEventListeners();
  }

  createContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
  }

  setupEventListeners() {
    // Auto-show notifications for events
    eventBus.on(Events.SOURCE_COMPLETED, (data) => {
      this.success(`✅ ${data.sourceName} atualizado`, 
        `${data.linksDiscovered} links descobertos em ${this.formatDuration(data.duration)}`);
    });

    eventBus.on(Events.SOURCE_FAILED, (data) => {
      this.error(`❌ Falha em ${data.sourceName}`, data.error);
    });

    eventBus.on(Events.CONFLICT_DETECTED, (data) => {
      this.warning('⚠️ Conflito detectado', 'Sincronizando com servidor...');
    });
  }

  show(message, options = {}) {
    const {
      type = 'info',
      title,
      duration = this.defaultDuration,
      dismissible = true,
    } = options;

    const toast = document.createElement('div');
    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    toast.className = `toast toast-${type}`;
    toast.dataset.id = id;
    toast.innerHTML = `
      <div class="toast-content">
        ${title ? `<div class="toast-title">${title}</div>` : ''}
        <div class="toast-message">${message}</div>
      </div>
      ${dismissible ? '<button class="toast-close">×</button>' : ''}
    `;

    // Progress bar
    if (duration > 0) {
      const progress = document.createElement('div');
      progress.className = 'toast-progress';
      toast.appendChild(progress);
    }

    // Event handlers
    if (dismissible) {
      toast.querySelector('.toast-close').addEventListener('click', () => {
        this.dismiss(id);
      });
    }

    this.container.appendChild(toast);
    this.toasts.set(id, { element: toast, timeout: null });

    // Auto-dismiss
    if (duration > 0) {
      const timeout = setTimeout(() => this.dismiss(id), duration);
      this.toasts.get(id).timeout = timeout;
    }

    // Animate in
    requestAnimationFrame(() => {
      toast.classList.add('show');
    });

    return id;
  }

  success(message, title) {
    return this.show(message, { type: 'success', title });
  }

  error(message, title) {
    return this.show(message, { type: 'error', title, duration: 8000 });
  }

  warning(message, title) {
    return this.show(message, { type: 'warning', title });
  }

  info(message, title) {
    return this.show(message, { type: 'info', title });
  }

  dismiss(id) {
    const toast = this.toasts.get(id);
    if (!toast) return;

    clearTimeout(toast.timeout);
    toast.element.classList.remove('show');
    
    setTimeout(() => {
      toast.element.remove();
      this.toasts.delete(id);
    }, 300);
  }

  formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}min`;
  }
}
```

### 5.2 Progress Component

```javascript
// ui/progress-bar.js

/**
 * Animated progress indicator for source operations
 */
export class ProgressBar {
  constructor(container) {
    this.container = container;
    this.element = this.createElement();
    container.appendChild(this.element);
    
    this.hide();
  }

  createElement() {
    const wrapper = document.createElement('div');
    wrapper.className = 'progress-wrapper';
    wrapper.innerHTML = `
      <div class="progress-bar">
        <div class="progress-fill"></div>
      </div>
      <div class="progress-text">
        <span class="progress-percent">0%</span>
        <span class="progress-detail"></span>
      </div>
    `;
    return wrapper;
  }

  setProgress(percent, detail = '') {
    const fill = this.element.querySelector('.progress-fill');
    const percentText = this.element.querySelector('.progress-percent');
    const detailText = this.element.querySelector('.progress-detail');

    fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    percentText.textContent = `${Math.round(percent)}%`;
    
    if (detail) {
      detailText.textContent = detail;
    }

    this.show();
  }

  setIndeterminate() {
    const fill = this.element.querySelector('.progress-fill');
    fill.classList.add('indeterminate');
    this.show();
  }

  complete(message = 'Concluído!') {
    this.setProgress(100);
    const detailText = this.element.querySelector('.progress-detail');
    detailText.textContent = message;
    
    setTimeout(() => this.hide(), 1500);
  }

  show() {
    this.element.classList.add('visible');
  }

  hide() {
    this.element.classList.remove('visible');
  }

  destroy() {
    this.element.remove();
  }
}
```

---

## 6. Integration with Existing Code

### 6.1 Enhanced API Client

```javascript
// api/api.js (enhanced)
import { eventBus, Events } from '../core/event-bus.js';
import { RetryPolicy } from '../core/retry-policy.js';
import { actionQueue } from '../sync/action-queue.js';

const API_BASE = '/api/v1';

/**
 * Enhanced fetch wrapper with retry logic
 */
async function apiFetch(endpoint, options = {}) {
  const retryPolicy = new RetryPolicy({
    maxRetries: options.retries ?? 3,
    baseDelay: 1000,
  });

  while (true) {
    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          ...options.headers,
        },
        ...options,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'Unknown error' }));
        throw new ApiError(error.message, response.status, error.code);
      }

      return await response.json();
    } catch (err) {
      const attempt = retryPolicy.nextAttempt();
      
      if (!attempt.shouldRetry || err.status >= 400 && err.status < 500) {
        throw err;
      }
      
      await delay(attempt.delay);
    }
  }
}

class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Enhanced GABI API Client with offline support
 */
export const api = {
  /**
   * List all sources
   */
  async listSources() {
    const result = await apiFetch('/sources');
    return result.data;
  },

  /**
   * Get source details (with local cache fallback)
   */
  async getSource(sourceId, { useCache = true } = {}) {
    // Try cache first if offline
    if (useCache && !navigator.onLine) {
      const { localCache } = await import('../sync/local-storage.js');
      const cached = localCache.get(sourceId);
      if (cached) return cached;
    }

    const result = await apiFetch(`/sources/${sourceId}`);
    
    // Update cache
    if (result.data) {
      const { localCache } = await import('../sync/local-storage.js');
      localCache.set(sourceId, result.data);
    }
    
    return result.data;
  },

  /**
   * Refresh source with offline queue support
   */
  async refreshSource(sourceId) {
    // Optimistic update
    eventBus.emit(Events.SOURCE_REFRESH_START, { sourceId });

    // If offline, queue for later
    if (!navigator.onLine) {
      const actionId = actionQueue.enqueue({
        type: 'REFRESH_SOURCE',
        payload: { sourceId },
      });
      
      return { 
        queued: true, 
        actionId,
        message: 'Ação enfileirada para quando a conexão for restaurada'
      };
    }

    // Execute immediately
    const result = await apiFetch(`/sources/${sourceId}/refresh`, {
      method: 'POST',
    });

    // Update cache with result
    const { localCache } = await import('../sync/local-storage.js');
    localCache.setLinks(sourceId, result.data?.links || []);

    return result.data;
  },

  /**
   * Health check with timeout
   */
  async health(timeout = 5000) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);
      
      const response = await fetch('/health', {
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);
      return response.ok;
    } catch {
      return false;
    }
  },

  /**
   * Get status for polling fallback
   */
  async getStatus(sourceIds = []) {
    const params = sourceIds.length > 0 
      ? `?sources=${sourceIds.join(',')}` 
      : '';
    const result = await apiFetch(`/sources/status${params}`);
    return result.data;
  },
};
```

### 6.2 Updated SourceList Component

```javascript
// components/source-list.js (real-time enhanced)
import { eventBus, Events } from '../core/event-bus.js';
import { ProgressBar } from '../ui/progress-bar.js';

export class SourceList {
  constructor(container) {
    this.container = container;
    this.onSourceClick = null;
    this.onRefreshClick = null;
    this.loadingSources = new Set();
    this.progressBars = new Map();
    
    this.setupEventListeners();
  }

  setupEventListeners() {
    // Real-time progress updates
    eventBus.on(Events.SOURCE_PROGRESS, ({ sourceId, progress, detail }) => {
      this.updateProgress(sourceId, progress, detail);
    });

    eventBus.on(Events.SOURCE_COMPLETED, ({ sourceId, linksDiscovered }) => {
      this.setLoading(sourceId, false);
      this.updateSourceLinks(sourceId, linksDiscovered);
      this.completeProgress(sourceId);
    });

    eventBus.on(Events.SOURCE_FAILED, ({ sourceId, error }) => {
      this.setLoading(sourceId, false);
      this.showError(sourceId, error);
    });
  }

  createCard(source) {
    const card = document.createElement('div');
    card.className = 'source-card';
    card.dataset.sourceId = source.id;
    
    const statusBadge = source.enabled 
      ? '<span class="status-badge enabled">● Ativo</span>' 
      : '<span class="status-badge disabled">● Inativo</span>';
    
    card.innerHTML = `
      <div class="source-header">
        <h3 class="source-name">${this.escapeHtml(source.name)} ${statusBadge}</h3>
        <span class="source-strategy">${source.strategy}</span>
      </div>
      <div class="source-provider">${this.escapeHtml(source.provider)}</div>
      <div class="progress-container"></div>
      <div class="source-meta">
        <span class="source-links-count" id="links-${source.id}">
          ${source.enabled ? 'Clique para ver detalhes' : 'Fonte desativada'}
        </span>
        <button class="btn btn-secondary btn-refresh" data-source-id="${source.id}" ${!source.enabled ? 'disabled' : ''}>
          🔄 Atualizar
        </button>
      </div>
    `;

    // Click handlers...
    card.addEventListener('click', (e) => {
      if (!e.target.closest('.btn-refresh') && this.onSourceClick) {
        this.onSourceClick(source.id);
      }
    });

    const refreshBtn = card.querySelector('.btn-refresh');
    refreshBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.onRefreshClick && !this.loadingSources.has(source.id)) {
        this.onRefreshClick(source.id);
      }
    });

    return card;
  }

  updateProgress(sourceId, progress, detail) {
    const card = this.container.querySelector(`[data-source-id="${sourceId}"]`);
    if (!card) return;

    let progressBar = this.progressBars.get(sourceId);
    if (!progressBar) {
      const container = card.querySelector('.progress-container');
      progressBar = new ProgressBar(container);
      this.progressBars.set(sourceId, progressBar);
    }

    progressBar.setProgress(progress, detail);
  }

  completeProgress(sourceId) {
    const progressBar = this.progressBars.get(sourceId);
    if (progressBar) {
      progressBar.complete();
      setTimeout(() => {
        progressBar.destroy();
        this.progressBars.delete(sourceId);
      }, 2000);
    }
  }

  showError(sourceId, error) {
    const card = this.container.querySelector(`[data-source-id="${sourceId}"]`);
    if (!card) return;

    const errorEl = document.createElement('div');
    errorEl.className = 'source-error';
    errorEl.textContent = `Erro: ${error}`;
    
    card.querySelector('.progress-container').appendChild(errorEl);
    
    setTimeout(() => errorEl.remove(), 5000);
  }

  // ... rest of existing methods
}
```

### 6.3 Updated main.js

```javascript
// main.js (with real-time initialization)
import { api } from './api/api.js';
import { SourceList } from './components/source-list.js';
import { SourceDetail } from './components/source-detail.js';
import { ConnectionManager } from './core/connection-manager.js';
import { ToastManager } from './ui/toast-manager.js';
import { localCache } from './sync/local-storage.js';
import { eventBus, Events } from './core/event-bus.js';

// Initialize components
const sourceList = new SourceList(document.getElementById('source-grid'));
const sourceDetail = new SourceDetail(document.getElementById('detail-panel'));
const toastManager = new ToastManager();

// Initialize connection manager
const connectionManager = new ConnectionManager();

// DOM elements
const sourceCountEl = document.getElementById('source-count');
const refreshAllBtn = document.getElementById('refresh-all');
const overlay = document.getElementById('overlay');
const closeDetailBtn = document.getElementById('close-detail');

// State
let sources = [];

// Initialize
async function init() {
  try {
    // Start real-time connection
    connectionManager.connect();

    // Check API health
    const isHealthy = await api.health();
    if (!isHealthy) {
      showError('API não está respondendo. Modo offline ativado.');
    }

    // Load sources (from cache if offline)
    await loadSources();
    
    // Setup event listeners
    setupEventListeners();
    
    // Setup connection status indicator
    setupConnectionStatus();
  } catch (error) {
    showError(error.message);
  }
}

async function loadSources() {
  try {
    sources = await api.listSources();
    sourceCountEl.textContent = `${sources.length} fontes disponíveis`;
    sourceList.render(sources);
  } catch (error) {
    showError(`Erro ao carregar fontes: ${error.message}`);
  }
}

function setupConnectionStatus() {
  const statusEl = document.createElement('div');
  statusEl.className = 'connection-status';
  document.querySelector('.header').appendChild(statusEl);

  eventBus.on(Events.CONNECTED, ({ transport }) => {
    statusEl.className = 'connection-status connected';
    statusEl.title = `Conectado (${transport})`;
  });

  eventBus.on(Events.DISCONNECTED, () => {
    statusEl.className = 'connection-status disconnected';
    statusEl.title = 'Desconectado';
  });

  eventBus.on(Events.RECONNECTING, ({ attempt, delay }) => {
    statusEl.className = 'connection-status reconnecting';
    statusEl.title = `Reconectando... (tentativa ${attempt})`;
  });
}

function setupEventListeners() {
  // Source card click -> show detail
  sourceList.onSourceClick = async (sourceId) => {
    try {
      const detail = await api.getSource(sourceId);
      sourceDetail.render(detail);
      openDetailPanel();
    } catch (error) {
      showError(`Erro ao carregar detalhes: ${error.message}`);
    }
  };

  // Refresh button with optimistic update
  sourceList.onRefreshClick = async (sourceId) => {
    try {
      sourceList.setLoading(sourceId, true);
      
      const result = await api.refreshSource(sourceId);
      
      if (result.queued) {
        toastManager.info(result.message, 'Modo Offline');
        sourceList.setLoading(sourceId, false);
        return;
      }
      
      // Don't reload immediately - wait for real-time update
      // The SOURCE_COMPLETED event will handle the UI update
    } catch (error) {
      showError(`Erro ao atualizar: ${error.message}`);
      sourceList.setLoading(sourceId, false);
    }
  };

  // Close detail panel
  closeDetailBtn.addEventListener('click', closeDetailPanel);
  overlay.addEventListener('click', closeDetailPanel);

  // Refresh all with queue support
  refreshAllBtn.addEventListener('click', async () => {
    refreshAllBtn.disabled = true;
    refreshAllBtn.innerHTML = '<span class="spinner"></span> Atualizando...';

    try {
      for (const source of sources.filter(s => s.enabled)) {
        await api.refreshSource(source.id);
      }
    } catch (error) {
      showError(`Erro ao atualizar fontes: ${error.message}`);
    } finally {
      refreshAllBtn.disabled = false;
      refreshAllBtn.innerHTML = '🔄 Atualizar Tudo';
    }
  });
}

// ... rest of helper functions

// Start
init();
```

---

## 7. Backend API Extensions Required

### 7.1 SSE Endpoint

```csharp
// src/Gabi.Api/Endpoints/SseEndpoints.cs
using System.Threading.Channels;

public static class SseEndpoints
{
    public static IEndpointConventionBuilder MapSseEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/v1/events");
        
        group.MapGet("/", async (
            HttpContext context,
            IProgressTracker progressTracker,
            string clientId,
            CancellationToken ct) =>
        {
            context.Response.Headers.Add("Content-Type", "text/event-stream");
            context.Response.Headers.Add("Cache-Control", "no-cache");
            context.Response.Headers.Add("Connection", "keep-alive");

            var channel = progressTracker.Subscribe(clientId);

            try
            {
                await foreach (var message in channel.Reader.ReadAllAsync(ct))
                {
                    await context.Response.WriteAsync($"event: {message.Type}\n");
                    await context.Response.WriteAsync($"data: {JsonSerializer.Serialize(message.Payload)}\n\n");
                    await context.Response.Body.FlushAsync(ct);
                }
            }
            finally
            {
                progressTracker.Unsubscribe(clientId);
            }
        });

        return group;
    }
}

// Progress message types
public record ProgressMessage(
    string Type, // progress, completed, failed, heartbeat
    object Payload
);

public record ProgressPayload(
    string SourceId,
    string SourceName,
    double Progress,
    int LinksDiscovered,
    string? Detail
);

public record CompletedPayload(
    string SourceId,
    string SourceName,
    int LinksDiscovered,
    TimeSpan Duration
);

public record FailedPayload(
    string SourceId,
    string SourceName,
    string Error
);
```

### 7.2 Status Polling Endpoint

```csharp
// Add to existing endpoints
group.MapGet("/status", async (
    [FromQuery] string[]? sources,
    ISourceCatalog catalog,
    CancellationToken ct) =>
{
    var statusList = new List<SourceStatusDto>();
    
    foreach (var sourceId in sources ?? Array.Empty<string>())
    {
        var status = await catalog.GetSourceStatusAsync(sourceId, ct);
        if (status != null)
            statusList.Add(status);
    }
    
    return Results.Ok(new ApiEnvelope<IReadOnlyList<SourceStatusDto>>(statusList));
});

public record SourceStatusDto(
    string SourceId,
    string Status, // idle, pending, running, completed, failed
    double Progress,
    int LinksDiscovered,
    string? Error,
    DateTime? LastUpdated
);
```

---

## 8. CSS Additions

```css
/* Add to style.css */

/* Connection Status Indicator */
.connection-status {
  position: fixed;
  top: 1rem;
  right: 1rem;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transition: all 0.3s ease;
}

.connection-status.connected {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}

.connection-status.disconnected {
  background: var(--error);
  box-shadow: 0 0 8px var(--error);
}

.connection-status.reconnecting {
  background: var(--warning);
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Progress Bar */
.progress-wrapper {
  margin: 1rem 0;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.progress-wrapper.visible {
  opacity: 1;
}

.progress-bar {
  height: 4px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent-gradient);
  border-radius: 2px;
  transition: width 0.3s ease;
  width: 0%;
}

.progress-fill.indeterminate {
  width: 30%;
  animation: indeterminate 1s infinite linear;
}

@keyframes indeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.progress-text {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

/* Toast Notifications */
.toast-container {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  max-width: 400px;
}

.toast {
  background: var(--glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--glass-border);
  border-radius: var(--border-radius);
  padding: 1rem;
  transform: translateX(120%);
  transition: transform 0.3s ease;
  position: relative;
  overflow: hidden;
}

.toast.show {
  transform: translateX(0);
}

.toast-success { border-left: 3px solid var(--success); }
.toast-error { border-left: 3px solid var(--error); }
.toast-warning { border-left: 3px solid var(--warning); }
.toast-info { border-left: 3px solid var(--accent-primary); }

.toast-title {
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.toast-message {
  color: var(--text-secondary);
  font-size: 0.875rem;
}

.toast-close {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
}

.toast-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--accent-primary);
  animation: toast-timer 5s linear forwards;
}

@keyframes toast-timer {
  from { width: 100%; }
  to { width: 0%; }
}

/* Source Error Message */
.source-error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid var(--error);
  border-radius: 4px;
  padding: 0.5rem;
  color: var(--error);
  font-size: 0.75rem;
  margin-top: 0.5rem;
}
```

---

## 9. Implementation Timeline

### Phase 1: Foundation (Week 1)
- [ ] Implement EventBus
- [ ] Create RetryPolicy
- [ ] Build ConnectionManager (SSE + polling)
- [ ] Add ToastManager
- [ ] Basic progress indicators

### Phase 2: Offline Support (Week 2)
- [ ] LocalStorageAdapter for discovered links
- [ ] ActionQueue for offline actions
- [ ] ConflictResolver
- [ ] Enhanced api.js with offline support

### Phase 3: Backend Integration (Week 3)
- [ ] SSE endpoint in Gabi.Api
- [ ] Progress tracking service
- [ ] Status polling endpoint
- [ ] Integration tests

### Phase 4: Polish (Week 4)
- [ ] Connection status UI
- [ ] Optimistic updates in SourceList
- [ ] Error recovery flows
- [ ] Performance optimization

---

## 10. Performance Considerations

| Metric | Target | Notes |
|--------|--------|-------|
| Connection latency | <100ms | Initial handshake |
| Message latency | <50ms | Server→Client event |
| Reconnection time | <5s | With exponential backoff |
| LocalStorage reads | <10ms | Cached in memory |
| Bundle size increase | <15KB | Gzipped |

### Memory Management
- Auto-cleanup completed progress bars
- LRU eviction for localStorage cache
- Debounced state updates

---

## 11. Testing Strategy

```javascript
// Example test patterns

describe('ConnectionManager', () => {
  test('falls back to polling when SSE fails', async () => {
    // Mock SSE failure
    // Assert polling is activated
  });
  
  test('reconnects with exponential backoff', async () => {
    // Simulate connection drop
    // Verify retry delays: 1s, 2s, 4s...
  });
});

describe('Offline Support', () => {
  test('queues actions when offline', async () => {
    // Set navigator.onLine = false
    // Trigger refresh action
    // Assert action is queued
  });
  
  test('processes queue when coming online', async () => {
    // Add actions to queue
    // Fire online event
    // Assert actions are processed
  });
});
```

---

## 12. Migration Guide

### From Current Code

1. **Add new files** in order:
   ```bash
   # Core
   web/src/core/event-bus.js
   web/src/core/retry-policy.js
   web/src/core/connection-manager.js
   web/src/core/state-manager.js
   
   # Sync
   web/src/sync/action-queue.js
   web/src/sync/local-storage.js
   web/src/sync/conflict-resolver.js
   
   # UI
   web/src/ui/toast-manager.js
   web/src/ui/progress-bar.js
   ```

2. **Update existing files**:
   - `api.js` - Add retry logic, offline support
   - `source-list.js` - Add progress listeners
   - `main.js` - Initialize connection manager

3. **Add CSS** from section 8

4. **Backend** - Add SSE endpoint

---

## Summary

This design provides:
- **Real-time updates** via SSE with polling fallback
- **Resilient connections** with exponential backoff reconnection
- **Offline support** with action queuing and conflict resolution
- **Optimistic UI** for immediate feedback
- **Persistent cache** for discovered links
- **Minimal bundle impact** (~15KB)

The architecture is modular, testable, and progressively enhanced - it works without JavaScript for basic functionality, and provides rich real-time features when available.
