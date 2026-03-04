FROM postgres:16-alpine

# Custom postgresql.conf tuned for Fly shared-cpu-4x (1GB RAM)
COPY postgresql.conf /etc/postgresql/postgresql.conf
COPY pg_hba.conf /etc/postgresql/pg_hba.conf

# Tell PG to use our custom config
CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf", "-c", "hba_file=/etc/postgresql/pg_hba.conf"]
