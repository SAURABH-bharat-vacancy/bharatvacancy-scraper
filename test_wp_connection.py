#!/usr/bin/env python3
"""
Test WordPress REST API connection
"""

import requests
import base64
import sys

# Change these to match your setup
WP_URL = "https://bharatvacancy.com"
WP_USER = "admin"
WP_PASS = "jgTxax8EXgL8DsYCIWkHL3c0"  # Replace with actual password (no spaces)

print("=" * 70)
print("WORDPRESS REST API CONNECTION TEST")
print("=" * 70)

print(f"\n📌 Testing connection to: {WP_URL}")
print(f"👤 User: {WP_USER}")
print(f"🔐 Password: {'*' * len(WP_PASS)}")

# Create auth header
credentials = f"{WP_USER}:{WP_PASS}"
encoded = base64.b64encode(credentials.encode()).decode()

headers = {
    'Authorization': f'Basic {encoded}',
    'Content-Type': 'application/json'
}

# Test 1: Check if REST API is accessible
print("\n" + "=" * 70)
print("TEST 1: Checking REST API accessibility")
print("=" * 70)

try:
    rest_url = f"{WP_URL}/wp-json/"
    response = requests.get(rest_url, timeout=10)
    
    if response.status_code == 200:
        print("✅ REST API is ACCESSIBLE")
        print(f"   Status: {response.status_code}")
    else:
        print(f"❌ REST API returned: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error: {str(e)}")

# Test 2: Check authentication
print("\n" + "=" * 70)
print("TEST 2: Checking authentication credentials")
print("=" * 70)

try:
    auth_url = f"{WP_URL}/wp-json/wp/v2/users/me"
    response = requests.get(auth_url, headers=headers, timeout=10)
    
    if response.status_code == 200:
        user_info = response.json()
        print("✅ AUTHENTICATION SUCCESSFUL")
        print(f"   User ID: {user_info.get('id')}")
        print(f"   Username: {user_info.get('username')}")
        print(f"   Name: {user_info.get('name')}")
        print(f"   Role: {user_info.get('roles')}")
    
    elif response.status_code == 401:
        print("❌ AUTHENTICATION FAILED (401)")
        print("   Your password or username is incorrect!")
        print(f"   Response: {response.text}")
    
    elif response.status_code == 403:
        print("❌ PERMISSION DENIED (403)")
        print("   User doesn't have permission to access API")
        print(f"   Response: {response.text}")
    
    else:
        print(f"❌ Unexpected error: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error: {str(e)}")

# Test 3: Try to create a test post
print("\n" + "=" * 70)
print("TEST 3: Testing post creation")
print("=" * 70)

try:
    post_url = f"{WP_URL}/wp-json/wp/v2/posts"
    
    test_post = {
        'title': f'Test Post - {requests.utils.quote("Scraper Connection Test")}',
        'content': '<p>This is a test post to verify API connection</p>',
        'status': 'draft'  # Create as draft, not published
    }
    
    response = requests.post(post_url, headers=headers, json=test_post, timeout=15)
    
    if response.status_code == 201:
        post_id = response.json().get('id')
        print(f"✅ POST CREATION SUCCESSFUL")
        print(f"   Test Post ID: {post_id}")
        print(f"   Status: Draft")
        print(f"\n   Note: This test post was created as 'Draft'.")
        print(f"   You can delete it from WordPress Posts page if needed.")
        
        # Try to delete it
        delete_url = f"{post_url}/{post_id}"
        delete_response = requests.delete(delete_url, headers=headers, params={'force': 'true'}, timeout=10)
        
        if delete_response.status_code == 200:
            print(f"   ✓ Test post was deleted automatically.")
    
    elif response.status_code == 400:
        error_msg = response.json().get('message', 'Unknown error')
        print(f"❌ BAD REQUEST (400)")
        print(f"   Error: {error_msg}")
    
    elif response.status_code == 401:
        print(f"❌ AUTHENTICATION FAILED (401)")
        print(f"   Check your password!")
    
    elif response.status_code == 403:
        print(f"❌ PERMISSION DENIED (403)")
        print(f"   User role might not have post creation permission")
    
    else:
        print(f"❌ Error: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error: {str(e)}")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print("""
If all tests passed (✅):
  → Your scraper should work on GitHub
  → Update GitHub secrets and run the workflow
  
If any test failed (❌):
  → Check the error message above
  → Common issues:
    1. Wrong Application Password
    2. User doesn't have Administrator role
    3. REST API is disabled
    4. Wrong WordPress URL
""")
print("=" * 70)
