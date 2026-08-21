#include "SerialProtocol.h"

SerialProtocol::SerialProtocol(Stream &serial)
  : _serial(serial), _lineLength(0), _queueHead(0), _queueCount(0) {}

void SerialProtocol::update() {
  // Stop consuming once the queue is full instead of parsing-then-
  // dropping: unread bytes just stay in the serial RX buffer until a
  // later update() call (after loop() has drained some commands via
  // getCommand()), so a burst that briefly outruns the queue is
  // delayed, not lost.
  while (_serial.available() > 0 && _queueCount < SP_QUEUE_SIZE) {
    char c = (char)_serial.read();

    if (c == '\n') {
      _lineBuffer[_lineLength] = '\0';
      parseLine();
      _lineLength = 0;
      continue;
    }
    if (c == '\r') {
      continue;  // tolerate CRLF line endings from the PC side
    }
    if (_lineLength < SP_LINE_BUFFER_SIZE - 1) {
      _lineBuffer[_lineLength++] = c;
    } else {
      // Line too long for the buffer -- drop it rather than overflow
      // or silently parse a truncated/garbled command.
      _lineLength = 0;
    }
  }
}

bool SerialProtocol::hasCommand() const {
  return _queueCount > 0;
}

Command SerialProtocol::getCommand() {
  Command cmd = _queue[_queueHead];
  _queueHead = (_queueHead + 1) % SP_QUEUE_SIZE;
  _queueCount--;
  return cmd;
}

void SerialProtocol::parseLine() {
  // Expected: "CMD <id> <TYPE> [args...]"
  if (_lineLength == 0) return;

  char *cmdWord = strtok(_lineBuffer, " ");
  if (cmdWord == nullptr || strcmp(cmdWord, "CMD") != 0) {
    return;  // not a line we understand -- ignore rather than guess
  }

  char *idWord = strtok(nullptr, " ");
  if (idWord == nullptr) return;

  char *typeWord = strtok(nullptr, " ");
  if (typeWord == nullptr) return;

  char *rest = strtok(nullptr, "");  // remainder of the line, if any

  if (_queueCount >= SP_QUEUE_SIZE) {
    // Defensive only: update()'s while-condition already stops reading
    // once the queue is full, so parseLine() shouldn't be reachable in
    // that state. Guard kept in case that invariant ever changes.
    return;
  }

  uint8_t tail = (_queueHead + _queueCount) % SP_QUEUE_SIZE;
  Command &slot = _queue[tail];

  slot.id = atol(idWord);
  strncpy(slot.type, typeWord, SP_TYPE_BUFFER_SIZE - 1);
  slot.type[SP_TYPE_BUFFER_SIZE - 1] = '\0';
  if (rest != nullptr) {
    strncpy(slot.args, rest, SP_ARGS_BUFFER_SIZE - 1);
    slot.args[SP_ARGS_BUFFER_SIZE - 1] = '\0';
  } else {
    slot.args[0] = '\0';
  }
  _queueCount++;
}

void SerialProtocol::sendAck(long id) {
  _serial.print("ACK ");
  _serial.print(id);
  _serial.println(" OK");
}

void SerialProtocol::sendError(long id, const char *reason) {
  _serial.print("ACK ");
  _serial.print(id);
  _serial.print(" ERR ");
  _serial.println(reason);
}
