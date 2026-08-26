#pragma once

// TEMPORARY shim: inlines RpcResponseBuilder from improv-wifi/sdk-cpp#34's follow up
// (https://github.com/improv-wifi/sdk-cpp/pull/43) so this branch builds and tests
// against Improv 1.2.6. Revert the commit adding this file once Improv 1.3.0 is
// released and the library pin is restored.

// Guarded so environments without the Improv library (for example the Zephyr
// clang-tidy environment, which analyzes every header) skip the shim entirely
#if __has_include(<improv.h>)
#include <improv.h>

#include <cstdint>
#include <cstring>
#include <span>

namespace improv {

// Maximum encoded RPC response size: command (1) + data length (1) + string data (up to 255,
// the data length field is a single byte) + trailing checksum byte (1)
inline constexpr size_t RPC_RESPONSE_MAX_SIZE = 258;

// Builds an RPC response into a caller-provided buffer with no heap allocation.
// Produces byte-identical output to build_rpc_response(): the trailing byte is the
// checksum when requested and 0x00 otherwise.
class RpcResponseBuilder {
 public:
  RpcResponseBuilder(std::span<uint8_t, RPC_RESPONSE_MAX_SIZE> buf, Command command) : buf_(buf) { buf_[0] = command; }

  // Appends one string entry (length byte + string bytes). Returns false and appends
  // nothing if the string does not fit in the response's 255 byte payload budget.
  bool add_string(const char *str) { return this->add_string(str, strlen(str)); }
  bool add_string(const char *str, size_t length) {
    // The length byte and string bytes must fit in the payload budget covered by the
    // single byte data length field, so the last usable position is one before the
    // trailing checksum byte
    if (this->pos_ + 1 + length > RPC_RESPONSE_MAX_SIZE - 1)
      return false;
    this->buf_[this->pos_++] = static_cast<uint8_t>(length);
    std::memcpy(this->buf_.data() + this->pos_, str, length);
    this->pos_ += length;
    return true;
  }

  // Writes the data length and trailing byte, then returns the finished response bytes.
  // Call at most once; the builder must not be reused afterwards.
  std::span<const uint8_t> finish(bool add_checksum = true) {
    this->buf_[1] = static_cast<uint8_t>(this->pos_ - 2);
    uint8_t trailing = 0;
    if (add_checksum) {
      uint32_t calculated_checksum = 0;
      for (size_t i = 0; i < this->pos_; i++) {
        calculated_checksum += this->buf_[i];
      }
      trailing = static_cast<uint8_t>(calculated_checksum & 0xFF);
    }
    this->buf_[this->pos_++] = trailing;
    return {this->buf_.data(), this->pos_};
  }

 private:
  std::span<uint8_t, RPC_RESPONSE_MAX_SIZE> buf_;
  uint16_t pos_{2};  // max 258, fits uint16_t
};

}  // namespace improv

#endif  // __has_include(<improv.h>)
