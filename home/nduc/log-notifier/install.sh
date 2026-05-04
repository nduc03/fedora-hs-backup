source ntfy-hs-log.env

trap 'unset PGPASSWORD DB_PASS' EXIT INT TERM ERR
export PGPASSWORD="$DB_PASS"

psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "CREATE DATABASE log_notifier;"

psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "
CREATE TABLE log_ntfy (
    id SERIAL PRIMARY KEY,
    last_check_log TIMESTAMP
);
INSERT INTO log_ntfy (id, last_check_log)
VALUES (1, CURRENT_TIMESTAMP - INTERVAL '5 minutes');
"

cp ntfy-hs-log.service ~/.config/systemd/user/ntfy-hs-log.service
cp ntfy-hs-log.timer ~/.config/systemd/user/ntfy-hs-log.timer
chmod 600 ntfy-hs-log.env
systemctl --user daemon-reload
systemctl --user enable --now ntfy-hs-log.timer