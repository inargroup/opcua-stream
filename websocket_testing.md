## MANDATORY: WebSocket Test Suite Implementation


### Required Test Implementation

CRITICAL: You MUST implement test functions for EVERY applicable item listed below. Do NOT skip any test case.

Use `python-socketio` client to connect and test Socket.IO functionality.

1. Connection Lifecycle Testing 
- Test successful connection to `/api/socket.io`
- Test connection failure with wrong path (should fail)
- Test disconnect event fires correctly
- Test connection status tracking
- Verify resource cleanup on disconnect

2. Room Management Testing (REQUIRED if rooms are implemented)
- Test `join_room` event with valid room_id
- Test `join_room` with missing/invalid room_id (should handle gracefully)
- Test multiple clients in same room
- Test clients in different rooms (messages isolated)
- Test leaving room on disconnect

3. Broadcasting & Real-time Sync Testing 
- Test `update` event received by all clients in same room
- Test messages NOT received by clients in different rooms
- Test real-time updates propagate immediately
- Test new joiners receive existing content (if applicable)
- Test simultaneous edits don't cause data loss
- Test debounced updates persist correctly (no data loss during rapid changes)

4. Error Handling Testing 
- Test malformed room_id handling
- Test missing data in events
- Test rapid connect/disconnect cycles
- Test socket connection status checks before emitting (verify `socket.connected` is checked)
- Test behavior when emitting during disconnect (should handle gracefully or queue)
- Test reconnection logic with exponential backoff

5. Multi-user Collaboration Testing (REQUIRED if collaboration exists)
- Test 2+ users in same room receive each other's updates
- Test no data loss with concurrent users
- Test user addition/removal from room
- Test access control if authentication exists

6. Performance Testing 
- Test multiple concurrent rooms
- Test rapid successive updates (no message loss)

### Backend Implementation Requirements

- Use `python-socketio` client library (NOT `requests`)
- Create test class with Socket.IO connection methods
- Test actual Socket.IO events (`connect`, `disconnect`, `join_room`, `update`)
- Include both positive and negative test cases
- Test only features that exist in the application
- Generate test report showing pass/fail for each category

---

## Playwright Frontend Testing

Use Playwright to test WebSocket functionality from the browser perspective.

1. Connection & UI State Testing 
- Test connection status indicator appears (connected/disconnected)
- Test UI enables/disables features based on connection state
- Test reconnection UI feedback on network interruption

2. Real-time Updates in UI 
- Test changes from User A appear in User B's browser immediately
- Test optimistic updates render before server confirmation
- Test UI updates don't cause flickering or re-renders

3. Multi-user Collaboration Flow (REQUIRED if collaboration exists)
- Test 2 browsers in same room see each other's edits
- Test presence indicators (user avatars, typing indicators)
- Test cursor positions sync across users (if applicable)

4. Error Handling & Edge Cases 
- Test UI behavior when socket disconnects mid-action
- Test queued actions sent after reconnection
- Test conflict resolution UI (e.g., merge conflicts, last-write-wins)
- Test component unmount properly disconnects socket (no memory leaks)

5. Room Management from UI (REQUIRED if rooms exist)
- Test joining room via URL/invite link
- Test room switching between different rooms
- Test leaving room on page navigation
