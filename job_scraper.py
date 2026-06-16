#!/usr/bin/env python3
"""
Bharat Vacancy - Government Job Scraper
Automatically scrapes and posts jobs to WordPress
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import os
import sys

# Government websites to scrape with updated valid paths
WEBSITES = {
    'SSC': {
        'url': 'https://ssc.gov.in',
        'category': 'SSC Jobs',
        'location': 'All India'
    },
    'IBPS': {
        'url': 'https://www.ibps.in/careers',
        'category': 'Banking Jobs',
        'location': 'All India'
    },
    'SBI': {
        'url': 'https://sbi.co.in',
        'category': 'Banking Jobs',
        'location': 'All India'
    },
    'RRB': {
        'url': 'https://rrbcdg.gov.in',
        'category': 'Railways Jobs',
        'location': 'All India'
    },
    'NDA': {
        'url': 'https://nda.ac.in/notifications',
        'category': 'Defence Jobs',
        'location': 'All India'
    }
}

class JobScraper:
    def __init__(self):
        self.jobs = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }
    
    def scrape_with_fallback(self, url, source_name, category, location):
        """Generic scraper targeting notification links"""
        try:
            # Add a realistic timeout and handle redirects safely
            response = requests.get(url, headers=self.headers, timeout=15, allow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Scan more links on the page so we pass navigation zones
            links = soup.find_all('a', limit=100)
            initial_count = len(self.jobs)
            
            # Words indicating a real job listing document
            target_keywords = ['advertisement', 'recruitment', 'notice', 'apply', 'job', 'vacancy', 'manager', 'officer', 'clerk', 'post']
            # Common main layout words to actively avoid
            exclude_keywords = ['home', 'about', 'contact', 'login', 'tender', 'gallery', 'sitemap', 'privacy', 'feedback']
            
            for link in links:
                title = link.get_text().strip()
                href = link.get('href', '')
                
                if len(title) < 8:
                    continue
                
                title_lower = title.lower()
                
                # Check if it contains general menu labels
                if any(ex in title_lower for ex in exclude_keywords):
                    continue
                    
                # Prioritize useful content matches or direct dynamic document links (.pdf)
                if any(kw in title_lower for kw in target_keywords) or '.pdf' in href.lower():
                    if href and ('http' in href or href.startswith('/') or href.startswith('.')):
                        
                        # Clean relative tracking endpoints
                        if href.startswith('.'):
                            href = href.lstrip('.')
                        if href.startswith('/'):
                            base_url = url.split('//')[0] + '//' + url.split('//')[1].split('/')[0]
                            href = base_url + href
                        
                        job = {
                            'title': title[:200],
                            'url': href,
                            'source': source_name,
                            'category': category,
                            'location': location,
                            'posted_date': datetime.now().strftime('%Y-%m-%d'),
                            'type': 'Permanent'
                        }
                        
                        # Avoid saving matching titles
                        if not any(j['title'] == job['title'] for j in self.jobs):
                            self.jobs.append(job)
                            print(f"✓ Found: {title[:50]}...")
            
            # Fallback mock notice if public portals block automated access 
            if len(self.jobs) == initial_count:
                fallback_job = {
                    'title': f"Latest {source_name} Recruitment Notifications & Active Vacancies",
                    'url': url,
                    'source': source_name,
                    'category': category,
                    'location': location,
                    'posted_date': datetime.now().strftime('%Y-%m-%d'),
                    'type': 'Permanent'
                }
                self.jobs.append(fallback_job)
                print(f"✓ Added general feed for: {source_name}")
                
            return len([j for j in self.jobs if j['source'] == source_name])
        
        except requests.exceptions.RequestException as e:
            print(f"✗ Error scraping {source_name}: {e}")
            # Ensure at least an endpoint bookmark link stays on file if the host times out
            fallback_job = {
                'title': f"Check Latest {source_name} Vacancies Directly",
                'url': url,
                'source': source_name,
                'category': category,
                'location': location,
                'posted_date': datetime.now().strftime('%Y-%m-%d'),
                'type': 'Permanent'
            }
            self.jobs.append(fallback_job)
            return 1
    
    def scrape_all_sources(self):
        """Scrape all job sources"""
        print("=" * 60)
        print("Starting Job Scraper Engine")
        print("=" * 60)
        
        for source, config in WEBSITES.items():
            print(f"\n🔍 Scraping {source}...")
            count = self.scrape_with_fallback(
                config['url'],
                source,
                config['category'],
                config['location']
            )
            print(f"   Stored {count} jobs from {source}")
        
        print("\n" + "=" * 60)
        print(f"✓ Total jobs compiled: {len(self.jobs)}")
        print("=" * 60)
        
        return self.jobs
    
    def save_to_json(self, filename='jobs_data.json'):
        """Save jobs to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.jobs, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Data saved to {filename}")
        return filename

def main():
    scraper = JobScraper()
    scraper.scrape_all_sources()
    scraper.save_to_json()
    print("\n✓ Scraper completed successfully!")

if __name__ == '__main__':
    main()
