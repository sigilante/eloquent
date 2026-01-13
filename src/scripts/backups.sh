#!/bin/bash

BACKUP_DIR="/var/www/elo-ranker/backups"
DB_DIR="/var/www/elo-ranker/databases"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup users
cp "$DB_DIR/users.db" "$BACKUP_DIR/users_$TIMESTAMP.db"

# Backup all global ratings (these are the shared community data)
for csv in "$DB_DIR"/*_global_ratings.csv; do
    if [ -f "$csv" ]; then
        basename=$(basename "$csv")
        cp "$csv" "$BACKUP_DIR/${basename%.csv}_$TIMESTAMP.csv"
    fi
done

# Delete backups older than 24 hours
find "$BACKUP_DIR" -type f -mmin +1440 -delete

echo "$(date): Backup complete" >> "$BACKUP_DIR/backup.log"
