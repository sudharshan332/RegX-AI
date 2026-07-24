"""
Migration: Add auto_test_details column to failed_testcase_analysis table

This migration adds a JSON column to store auto test fix suggestions,
status tracking, and change request information.

Created: 2026-07-05
Author: Enhanced Intelligent Triage Flow Implementation
"""

def upgrade(connection):
    """Apply the migration."""
    
    # SQL commands to execute
    commands = [
        """
        ALTER TABLE failed_testcase_analysis 
        ADD COLUMN auto_test_details JSON DEFAULT NULL
        """,
        
        """
        CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_auto_fix_status 
        ON failed_testcase_analysis ((auto_test_details->>'$.fix_status'))
        """,
        
        """
        CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_fix_type
        ON failed_testcase_analysis ((auto_test_details->>'$.fix_suggestion.fix_type'))
        """
    ]
    
    # Execute each command
    cursor = connection.cursor()
    
    try:
        for command in commands:
            cursor.execute(command)
        
        connection.commit()
        print("✅ Successfully added auto_test_details column and indexes")
        
    except Exception as e:
        connection.rollback()
        print(f"❌ Migration failed: {str(e)}")
        raise
    
    finally:
        cursor.close()


def downgrade(connection):
    """Rollback the migration."""
    
    commands = [
        "DROP INDEX IF EXISTS idx_failed_testcase_analysis_fix_type",
        "DROP INDEX IF EXISTS idx_failed_testcase_analysis_auto_fix_status",
        "ALTER TABLE failed_testcase_analysis DROP COLUMN auto_test_details"
    ]
    
    cursor = connection.cursor()
    
    try:
        for command in commands:
            cursor.execute(command)
        
        connection.commit()
        print("✅ Successfully rolled back auto_test_details column migration")
        
    except Exception as e:
        connection.rollback()
        print(f"❌ Rollback failed: {str(e)}")
        raise
    
    finally:
        cursor.close()


# Migration metadata
MIGRATION_ID = "001_add_auto_test_details_column"
MIGRATION_DESCRIPTION = "Add auto_test_details JSON column to failed_testcase_analysis table"
DEPENDS_ON = []  # No dependencies

# Example usage for different database systems
DATABASE_SPECIFIC_SQL = {
    "postgresql": {
        "add_column": """
            ALTER TABLE failed_testcase_analysis 
            ADD COLUMN auto_test_details JSONB DEFAULT NULL
        """,
        "add_index_status": """
            CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_auto_fix_status 
            ON failed_testcase_analysis ((auto_test_details->>'fix_status'))
        """,
        "add_index_type": """
            CREATE INDEX IF NOT EXISTS idx_failed_testcase_analysis_fix_type
            ON failed_testcase_analysis ((auto_test_details->>'fix_suggestion'->>'fix_type'))
        """
    },
    
    "mysql": {
        "add_column": """
            ALTER TABLE failed_testcase_analysis 
            ADD COLUMN auto_test_details JSON DEFAULT NULL
        """,
        "add_index_status": """
            CREATE INDEX idx_failed_testcase_analysis_auto_fix_status 
            ON failed_testcase_analysis ((auto_test_details->>'$.fix_status'))
        """,
        "add_index_type": """
            CREATE INDEX idx_failed_testcase_analysis_fix_type
            ON failed_testcase_analysis ((auto_test_details->>'$.fix_suggestion.fix_type'))
        """
    },
    
    "sqlite": {
        "add_column": """
            ALTER TABLE failed_testcase_analysis 
            ADD COLUMN auto_test_details TEXT DEFAULT NULL
        """,
        # SQLite doesn't support JSON path indexes, so we skip them
        "note": "SQLite doesn't support JSON indexes. Consider upgrading to PostgreSQL for better JSON performance."
    }
}


def upgrade_for_database(connection, db_type="mysql"):
    """Apply migration for specific database type."""
    
    if db_type not in DATABASE_SPECIFIC_SQL:
        raise ValueError(f"Unsupported database type: {db_type}")
    
    sql_commands = DATABASE_SPECIFIC_SQL[db_type]
    cursor = connection.cursor()
    
    try:
        # Add column
        cursor.execute(sql_commands["add_column"])
        
        # Add indexes (if supported)
        if "add_index_status" in sql_commands:
            cursor.execute(sql_commands["add_index_status"])
        
        if "add_index_type" in sql_commands:
            cursor.execute(sql_commands["add_index_type"])
        
        connection.commit()
        print(f"✅ Successfully applied migration for {db_type}")
        
        # Show any notes
        if "note" in sql_commands:
            print(f"ℹ️  Note: {sql_commands['note']}")
        
    except Exception as e:
        connection.rollback()
        print(f"❌ Migration failed for {db_type}: {str(e)}")
        raise
    
    finally:
        cursor.close()


if __name__ == "__main__":
    """
    Example usage:
    
    # For MySQL/MariaDB
    import mysql.connector
    conn = mysql.connector.connect(host='localhost', user='user', password='pass', database='regx')
    upgrade_for_database(conn, 'mysql')
    
    # For PostgreSQL
    import psycopg2
    conn = psycopg2.connect(host='localhost', user='user', password='pass', database='regx')
    upgrade_for_database(conn, 'postgresql')
    
    # For SQLite
    import sqlite3
    conn = sqlite3.connect('regx.db')
    upgrade_for_database(conn, 'sqlite')
    """
    print("Migration script ready. Import and call upgrade_for_database() with your connection.")
    print("Supported database types: mysql, postgresql, sqlite")