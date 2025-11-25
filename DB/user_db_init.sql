/*--Inizializza il database con due tabelle:
    --users (email PK, username, iban, codice fiscale)
    --interests (email FK, airport code)*/

CREATE DATABASE IF NOT EXISTS userdb;
USE userdb;

CREATE TABLE IF NOT EXISTS users
(
    email VARCHAR(255) PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    CONSTRAINT uq_users_username UNIQUE (username)
);

-- interests table moved to datadb (see data_db_collector_init.sql)

/* At-most-once request log: stores processed request IDs per operation */
CREATE TABLE IF NOT EXISTS request_log
(
    request_id VARCHAR(255) PRIMARY KEY,
    operation VARCHAR(32) NOT NULL,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
