# circuit_breaker.py

import time
import threading

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30, expected_exception=Exception):
        """
        Initializes a new instance of the CircuitBreaker class.

        Parameters:
        - failure_threshold (int): Number of consecutive failures allowed before opening the circuit.
        - recovery_timeout (int): Time in seconds to wait before attempting to reset the circuit.
        - expected_exception (Exception): The exception type that triggers a failure count increment.
        """
        self.failure_threshold = failure_threshold          # Threshold for failures to open the circuit
        self.recovery_timeout = recovery_timeout            # Timeout before attempting to reset the circuit
        self.expected_exception = expected_exception        # Exception type to monitor
        self.failure_count = 0                              # Counter for consecutive failures
        self.last_failure_time = None                       # Timestamp of the last failure
        self.state = 'CLOSED'                               # Initial state of the circuit
        self.lock = threading.Lock()                        # Lock to ensure thread-safe operations

    def call(self, func, *args, **kwargs):
        """
        Executes the provided function within the circuit breaker context.

        Parameters:
        - func (callable): The function to execute.
        - *args: Variable length argument list for the function.
        - **kwargs: Arbitrary keyword arguments for the function.

        Returns:
        - The result of the function call if successful.

        Raises:
        - CircuitBreakerOpenException: If the circuit is open and calls are not allowed.
        - Exception: Re-raises any exceptions thrown by the function.
        """
        with self.lock:  # Ensure thread-safe access to shared variables
            if self.state == 'OPEN':
                # Calculate the time elapsed since the last failure
                time_since_failure = time.time() - self.last_failure_time
                if time_since_failure > self.recovery_timeout:
                    # Transition to HALF_OPEN state after recovery timeout
                    self.state = 'HALF_OPEN'
                else:
                    # Circuit is still open; deny the call
                    raise CircuitBreakerOpenException("Circuit is open. Call denied.")
            
            try:
                # Attempt to execute the function
                result = func(*args, **kwargs)
            except self.expected_exception as e:
                # Function raised an expected exception; increment failure count
                self.failure_count += 1
                self.last_failure_time = time.time()  # Update the last failure timestamp
                if self.failure_count >= self.failure_threshold:
                    # Failure threshold reached; open the circuit
                    self.state = 'OPEN'
                raise e  # Re-raise the exception to the caller
            else:
                # Function executed successfully
                if self.state == 'HALF_OPEN':
                    # Success in HALF_OPEN state; reset the circuit to CLOSED
                    self.state = 'CLOSED'
                    self.failure_count = 0  # Reset failure count
                return result  # Return the successful result

class CircuitBreakerOpenException(Exception):
    """Custom exception raised when the circuit breaker is open."""
    pass
