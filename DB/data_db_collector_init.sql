/*--inizializza il DB data collector con la seguente tabella flights:
    --id(chiave primaria);
    --airport_code;
    --flight_number;
    --departure_arrival_date;
*/
CREATE TABLE IF NOT EXISTS flights
(
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    airport_code VARCHAR(10) NOT NULL,
    flight_number VARCHAR(20) NOT NULL,
    departure_arrival_date DATETIME NOT NULL
);
