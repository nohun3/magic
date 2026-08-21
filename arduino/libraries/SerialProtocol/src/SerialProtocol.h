// Non-blocking line-buffered parser for the PC <-> Arduino command
// protocol: "CMD <id> <TYPE> [args...]" in, "ACK <id> OK" / "ACK <id>
// ERR <reason>" out.
//
// update() only ever consumes whatever bytes are currently sitting in
// the serial receive buffer and returns immediately -- it never waits
// for more data, so calling it every loop() iteration never stalls the
// rest of the sketch (scheduler, HID output, etc.).
//
// Parsed commands go into a small ring buffer (SP_QUEUE_SIZE slots), not
// a single pending-command variable: if two full lines arrive before
// loop() drains them, a single-slot design would silently overwrite the
// first with the second and lose it. With the queue, loop() just needs
// to call hasCommand()/getCommand() in a `while` (not `if`) to drain
// everything that arrived, in order.
//
// If the queue does fill up (SP_QUEUE_SIZE consecutive unconsumed
// commands -- shouldn't happen as long as loop() drains it every
// iteration, which it does), newly parsed commands are dropped rather
// than corrupting the buffer. There's no slot to report that back to
// the PC from inside parseLine(); keep SP_QUEUE_SIZE comfortably above
// the largest realistic per-loop burst.
//
// Uses fixed-size char buffers instead of the Arduino String class on
// purpose: String's heap allocations fragment memory over a long
// unattended run, which is exactly the failure mode this firmware needs
// to avoid.
#ifndef SERIAL_PROTOCOL_H
#define SERIAL_PROTOCOL_H

#include <Arduino.h>

#define SP_LINE_BUFFER_SIZE 64
#define SP_TYPE_BUFFER_SIZE 16
#define SP_ARGS_BUFFER_SIZE 40
#define SP_QUEUE_SIZE 8

struct Command {
  long id;
  char type[SP_TYPE_BUFFER_SIZE];
  char args[SP_ARGS_BUFFER_SIZE];
};

class SerialProtocol {
public:
  explicit SerialProtocol(Stream &serial);

  // Call every loop() iteration. Reads whatever bytes are currently
  // available and returns; never blocks waiting for more.
  void update();

  // True if at least one complete command is waiting to be consumed.
  bool hasCommand() const;

  // Dequeues and returns the oldest pending command. Only call this
  // when hasCommand() is true. Call it in a loop (`while (hasCommand())`)
  // to drain everything that's arrived, not just one per loop() pass.
  Command getCommand();

  void sendAck(long id);
  void sendError(long id, const char *reason);

private:
  Stream &_serial;
  char _lineBuffer[SP_LINE_BUFFER_SIZE];
  uint8_t _lineLength;

  Command _queue[SP_QUEUE_SIZE];
  uint8_t _queueHead;   // index of the oldest queued command
  uint8_t _queueCount;  // number of commands currently queued

  void parseLine();
};

#endif
