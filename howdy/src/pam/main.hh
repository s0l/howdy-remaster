#ifndef MAIN_H_
#define MAIN_H_

#include <cstring>
#include <string>
#include <unistd.h>
#include <cstdint>

enum class ConfirmationType : std::uint8_t { Unset, Howdy, Pam };
enum class Workaround : std::uint8_t { Off, Input, Native };

// Exit status codes returned by the compare process
enum CompareError : std::uint8_t {
  NO_FACE_MODEL = 10,
  TIMEOUT_REACHED = 11,
  ABORT = 12,
  TOO_DARK = 13,
  INVALID_DEVICE = 14,
  RUBBERSTAMP = 15
};

inline auto get_workaround(const std::string &workaround) -> Workaround {
  if (workaround == "input") {
    return Workaround::Input;
  }

  if (workaround == "native") {
    return Workaround::Native;
  }

  return Workaround::Off;
}

inline auto is_safe_username(const char *username) -> bool {
  if (username == nullptr) {
    return false;
  }

  std::string user(username);
  if (user.empty() || user == "." || user == "..") {
    return false;
  }

  for (unsigned char character : user) {
    if (character < 32 || character == 127 || character == '/' ||
        character == '\\') {
      return false;
    }
  }

  return true;
}

/**
 * Check if an environment variable exists either in the environ array or using
 * getenv.
 * @param name The name of the environment variable.
 * @return The value of the environment variable or nullptr if it doesn't exist
 * or environ is nullptr.
 * @note This function was created because `getenv` wasn't working properly in
 * some contexts (like sudo).
 */
auto checkenv(const char *name) -> bool {
  if (std::getenv(name) != nullptr) {
    return true;
  }

  auto len = strlen(name);

  for (char **env = environ; *env != nullptr; env++) {
    if (strncmp(*env, name, len) == 0) {
      return true;
    }
  }

  return false;
}

#endif // MAIN_H_
