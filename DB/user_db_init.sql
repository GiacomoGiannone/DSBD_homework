--Inizializza il database con due tabelle:
    --users (email PK, username, iban, codice fiscale)
    --interests (email FK, airport code)

CREATE TABLE IF NOT EXISTS users
(
    email TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    iban TEXT NOT NULL,
    codice_fiscale TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interests
(
    email TEXT NOT NULL,
    airport_code TEXT NOT NULL,
    PRIMARY KEY (email, airport_code),
    FOREIGN KEY (email),
        REFERENCES users(email)
        ON DELETE CASCADE
);