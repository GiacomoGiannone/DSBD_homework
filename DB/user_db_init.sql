/*--Inizializza il database con due tabelle:
    --users (email PK, username, iban, codice fiscale)
    --interests (email FK, airport code)*/

CREATE TABLE IF NOT EXISTS users
(
    email VARCHAR(255) PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    iban VARCHAR(50) DEFAULT NULL,
    codice_fiscale VARCHAR(16) DEFAULT NULL,
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS interests
(
    email VARCHAR(255) NOT NULL,
    airport_code VARCHAR(10) NOT NULL,
    PRIMARY KEY (email, airport_code),
    FOREIGN KEY (email) REFERENCES users(email) ON DELETE CASCADE
);
