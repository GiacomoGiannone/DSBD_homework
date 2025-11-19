-- Recreate flights table to the new schema expected by DataCollector
USE datadb;

DROP TABLE IF EXISTS flights;

CREATE TABLE IF NOT EXISTS flights
(
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    icao24 VARCHAR(32) NOT NULL,
    callsign VARCHAR(32),
    departure_airport VARCHAR(10),
    arrival_airport VARCHAR(10),
    departure_time INT,
    arrival_time INT,
    flight_type ENUM('DEPARTURE','ARRIVAL') NOT NULL,
    last_refresh TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_flight (icao24, departure_time, arrival_time, departure_airport, arrival_airport, flight_type),
    KEY idx_departure (departure_airport),
    KEY idx_arrival (arrival_airport)
);
