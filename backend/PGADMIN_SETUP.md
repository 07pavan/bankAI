# pgAdmin 4 Connection Guide for BankAI

## Connection Details

Use these settings to connect pgAdmin 4 to your BankAI PostgreSQL database:

### Server Connection Settings

1. **Right-click** on "Servers" in pgAdmin 4
2. Select **Create > Server**
3. Fill in the following details:

#### General Tab
- **Name**: `BankAI Local`

#### Connection Tab
- **Host name/address**: `localhost`
- **Port**: `5432`
- **Maintenance database**: `postgres`
- **Username**: `postgres`
- **Password**: `2004pavan`
- **Save password**: ✅ (Check this box)

#### Advanced Tab (Optional)
- **DB restriction**: `bankai_db` (to show only your database)

### Quick Connection Test

You can test the connection from command line:

```powershell
psql -U postgres -d bankai_db
# Enter password: 2004pavan
```

### Database Information

- **Database Name**: `bankai_db`
- **Tables**:
  - `users` - User authentication records
  - `kyc_submissions` - KYC submissions with encrypted data
  - `alembic_version` - Migration tracking

### Viewing Data in pgAdmin

After connecting, navigate to:
```
Servers > BankAI Local > Databases > bankai_db > Schemas > public > Tables
```

You can:
- Right-click on a table → **View/Edit Data** → **All Rows**
- Run SQL queries in the **Query Tool**

### Sample Queries

```sql
-- View all users
SELECT * FROM users;

-- View all KYC submissions
SELECT id, user_id, status, created_at 
FROM kyc_submissions 
ORDER BY created_at DESC;

-- Count submissions by status
SELECT status, COUNT(*) 
FROM kyc_submissions 
GROUP BY status;

-- Check active connections
SELECT * FROM pg_stat_activity 
WHERE datname = 'bankai_db';
```

### Troubleshooting

**If connection fails:**
1. Verify PostgreSQL is running: `Get-Service postgresql*`
2. Check if port 5432 is open: `netstat -an | findstr 5432`
3. Verify password is correct: `2004pavan`
4. Ensure `pg_hba.conf` allows local connections

**Connection String Format:**
```
postgresql://postgres:2004pavan@localhost:5432/bankai_db
```

---

**Status**: PostgreSQL is running and accepting connections. You can now connect pgAdmin 4 using the settings above.
