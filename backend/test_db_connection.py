"""
Test database connectivity and configuration
Run this to verify PostgreSQL connection before starting the server
"""

import sys
from sqlalchemy import create_engine, text
from app.core.config import settings

def test_database_connection():
    """Test PostgreSQL database connection"""
    print("=" * 60)
    print("BankAI Database Connection Test")
    print("=" * 60)
    
    # Display configuration
    print(f"\n📋 Configuration:")
    print(f"   Database URL: {settings.DATABASE_URL}")
    print(f"   App Name: {settings.APP_NAME}")
    print(f"   App Version: {settings.APP_VERSION}")
    
    # Test connection
    print(f"\n🔌 Testing PostgreSQL connection...")
    try:
        engine = create_engine(settings.DATABASE_URL)
        
        with engine.connect() as connection:
            # Test basic query
            result = connection.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            
            print(f"✅ Connection successful!")
            print(f"   PostgreSQL Version: {version[:50]}...")
            
            # Check if database exists
            result = connection.execute(text("SELECT current_database();"))
            db_name = result.fetchone()[0]
            print(f"   Connected to database: {db_name}")
            
            # Check if tables exist
            result = connection.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """))
            tables = result.fetchall()
            
            if tables:
                print(f"\n📊 Existing tables:")
                for table in tables:
                    print(f"   - {table[0]}")
            else:
                print(f"\n⚠️  No tables found. Run migrations: alembic upgrade head")
            
            return True
            
    except Exception as e:
        print(f"❌ Connection failed!")
        print(f"   Error: {str(e)}")
        print(f"\n💡 Troubleshooting:")
        print(f"   1. Check if PostgreSQL is running: Get-Service postgresql*")
        print(f"   2. Verify DATABASE_URL in .env file")
        print(f"   3. Ensure database 'bankai_db' exists")
        print(f"   4. Install psycopg2: pip install psycopg2-binary")
        return False

def test_encryption():
    """Test encryption configuration"""
    print(f"\n🔐 Testing encryption configuration...")
    try:
        from app.core.encryption import encryption_service
        
        test_data = "123456789012"
        encrypted = encryption_service.encrypt_aadhaar(test_data)
        decrypted = encryption_service.decrypt_aadhaar(encrypted)
        
        if decrypted == test_data:
            print(f"✅ Encryption working correctly!")
            print(f"   Test: {test_data} -> {encrypted[:30]}... -> {decrypted}")
        else:
            print(f"❌ Encryption test failed!")
            return False
            
    except Exception as e:
        print(f"❌ Encryption test failed: {str(e)}")
        return False
    
    return True

def test_jwt():
    """Test JWT configuration"""
    print(f"\n🔑 Testing JWT configuration...")
    try:
        from app.core.security import create_access_token
        
        token = create_access_token(data={"sub": "1"})
        
        if token:
            print(f"✅ JWT token generation working!")
            print(f"   Sample token: {token[:50]}...")
        else:
            print(f"❌ JWT token generation failed!")
            return False
            
    except Exception as e:
        print(f"❌ JWT test failed: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    print("\n")
    
    # Run all tests
    db_ok = test_database_connection()
    enc_ok = test_encryption()
    jwt_ok = test_jwt()
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Database Connection: {'✅ PASS' if db_ok else '❌ FAIL'}")
    print(f"Encryption:          {'✅ PASS' if enc_ok else '❌ FAIL'}")
    print(f"JWT Authentication:  {'✅ PASS' if jwt_ok else '❌ FAIL'}")
    
    if db_ok and enc_ok and jwt_ok:
        print("\n🎉 All tests passed! Your backend is ready to run.")
        print("   Start server: python -m app.main")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Please fix the issues above.")
        sys.exit(1)
