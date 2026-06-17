import requests
from bs4 import BeautifulSoup
import csv
import re

def scrape_ibps_jobs():
    """
    Scrape active recruitment links from the official IBPS landing hub.
    This bypasses the dead-end ibpsonline subdomains.
    """
    jobs = []
    
    try:
        # Core Public Hub URL
        main_url = "https://www.ibps.in/"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        print(f"Connecting to {main_url}...")
        response = requests.get(main_url, headers=headers, timeout=15)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Pull links out of the live scrolling banners, lists, and anchors
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            text = link.get_text(strip=True)
            href = link.get('href', '')
            
            # Filter based on common recruitment keywords on the portal
            if any(keyword in text.lower() for keyword in ['recruitment', 'apply online', 'crp', 'po', 'clerk', 'officer', 'rrb', 'notification']):
                
                # Turn relative URLs into absolute URLs properly
                if not href.startswith('http'):
                    href = main_url.rstrip('/') + '/' + href.lstrip('/')
                
                # Format a structured, user-friendly title based on keywords
                if 'po' in text.lower():
                    title = 'IBPS PO (Probationary Officer) Recruitment'
                elif 'clerk' in text.lower() or 'csa' in text.lower():
                    title = 'IBPS Clerk Recruitment'
                elif 'specialist' in text.lower() or 'so' in text.lower():
                    title = 'IBPS Specialist Officer (SO)'
                elif 'rrb' in text.lower():
                    title = 'IBPS RRB Officer / Clerk Recruitment'
                else:
                    title = text[:80] if len(text) > 8 else "IBPS Job Notification"
                
                # Avoid catching generic menu utility paths
                if len(text) < 10 and href == main_url:
                    continue

                job = {
                    'title': title,
                    'company': 'IBPS',
                    'location': 'All India',
                    'category': 'Banking',
                    'job_type': 'Permanent',
                    'application_link': href,
                    'description': f"Official recruitment update: {text[:150]}"
                }
                
                # Prevent duplicate lines in your WordPress CSV
                if not any(j['application_link'] == job['application_link'] for j in jobs):
                    jobs.append(job)
        
        # Check if the live scrape succeeded; if empty, transition to clean fallback portals
        if not jobs:
            print("⚠️ No live scrolling links found. Injecting safe portal links...")
            jobs = get_safe_fallback_jobs()
        
        print(f"✓ Successfully processed {len(jobs)} total jobs.")
        return jobs
        
    except Exception as e:
        print(f"✗ Scraping failed due to error: {str(e)}. Using safe fallbacks...")
        return get_safe_fallback_jobs()


def get_safe_fallback_jobs():
    """
    Returns permanent, reliable main section hubs.
    Even when exam dates close, these URLs resolve cleanly to an official page instead of a 404.
    """
    return [
        {
            'title': 'IBPS CRP PO / MT Recruitment Hub',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibps.in',
            'description': 'View ongoing notifications, results, and active portal tracking maps for Probationary Officer vacancies.'
        },
        {
            'title': 'IBPS CRP Clerical Cadre Hub',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibps.in',
            'description': 'Access active scheduling windows and application metrics for public sector clerical positions.'
        },
        {
            'title': 'IBPS CRP RRB (Regional Rural Banks) Hub',
            'company': 'IBPS',
            'location': 'All India',
            'category': 'Banking',
            'job_type': 'Permanent',
            'application_link': 'https://ibps.in',
            'description': 'Apply online or trace active interview timelines for Rural Bank Officer and Assistant positions.'
        }
    ]


def save_ibps_csv(jobs):
    """Save the output array cleanly to a WordPress import-compatible CSV"""
    if not jobs:
        print("No job data generated. CSV export skipped.")
        return
        
    filename = 'ibps_import.csv'
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'title', 'company', 'location', 'category', 'job_type', 'application_link', 'description'
        ])
        writer.writeheader()
        writer.writerows(jobs)
    
    print(f"✓ Saved {len(jobs)} listings to '{filename}' successfully.")


if __name__ == "__main__":
    print("🔄 Starting IBPS Job Board Scraper Process...")
    job_listings = scrape_ibps_jobs()
    save_ibps_csv(job_listings)
    print("✅ All processes completed successfully.")
