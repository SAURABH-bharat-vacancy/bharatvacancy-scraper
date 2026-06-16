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

# Government websites to scrape
WEBSITES = {
    'SSC': {
        'url': 'https://ssc.nic.in/notifications',
        'category': 'SSC Jobs',
        'location': 'All India'
    },
    'IBPS': {
        'url': 'https://www.ibps.in/careers',
        'category': 'Banking Jobs',
        'location': 'All India'
    },
    'SBI': {
        'url': 'https://www.sbi.co.in/careers',
        'category': 'Banking Jobs',
        'location': 'All India'
    },
    'RRB': {
        'url': 'https://www.rrbcdg.gov.in',
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def scrape_with_fallback(self, url, source_name, category, location):
        """Generic scraper with error handling"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find all links (generic approach)
            links = soup.find_all('a', limit=10)
            
            for link in links:
                title = link.get_text().strip()
                href = link.get('href', '')
                
                # Skip empty or navigation links
                if len(title) < 5 or title.lower() in ['home', 'about', 'contact', 'login']:
                    continue
                
                if href and ('http' in href or href.startswith('/')):
                    if href.startswith('/'):
                        href = url.split('/')[0] + '//' + url.split('/')[2] + href
                    
                    job = {
                        'title': title[:200],  # Limit title length
                        'url': href,
                        'source': source_name,
                        'category': category,
                        'location': location,
                        'posted_date': datetime.now().strftime('%Y-%m-%d'),
                        'type': 'Permanent'
                    }
                    
                    # Avoid duplicates
                    if not any(j['title'] == job['title'] for j in self.jobs):
                        self.jobs.append(job)
                        print(f"✓ Found: {title[:50]}...")
            
            return len([j for j in self.jobs if j['source'] == source_name])
        
        except requests.exceptions.RequestException as e:
            print(f"✗ Error scraping {source_name}: {e}")
            return 0
    
    def scrape_all_sources(self):
        """Scrape all job sources"""
        print("=" * 60)
        print("Starting Job Scraper")
        print("=" * 60)
        
        for source, config in WEBSITES.items():
            print(f"\n🔍 Scraping {source}...")
            count = self.scrape_with_fallback(
                config['url'],
                source,
                config['category'],
                config['location']
            )
            print(f"   Found {count} jobs from {source}")
        
        print("\n" + "=" * 60)
        print(f"✓ Total jobs scraped: {len(self.jobs)}")
        print("=" * 60)
        
        return self.jobs
    
    def save_to_json(self, filename='jobs_data.json'):
        """Save jobs to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.jobs, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Data saved to {filename}")
        return filename
    
    def post_to_wordpress(self, wp_url, wp_user, wp_pass):
        """
        Post jobs to WordPress using REST API
        This requires WordPress REST API to be enabled
        """
        try:
            from wordpress_rest_client_pt import WordPressClient
            
            print(f"\n📤 Posting to WordPress...")
            
            client = WordPressClient(
                url=wp_url,
                user=wp_user,
                password=wp_pass
            )
            
            for job in self.jobs[:10]:  # Post first 10 jobs
                try:
                    post_data = {
                        'title': job['title'],
                        'content': f"""
                        <p><strong>Position:</strong> {job['title']}</p>
                        <p><strong>Source:</strong> {job['source']}</p>
                        <p><strong>Location:</strong> {job['location']}</p>
                        <p><strong>Category:</strong> {job['category']}</p>
                        <p><a href="{job['url']}" target="_blank">View Full Details</a></p>
                        """,
                        'status': 'publish',
                        'type': 'post'
                    }
                    
                    # Create post
                    response = client.create_post(post_data)
                    print(f"  ✓ Posted: {job['title'][:40]}...")
                
                except Exception as e:
                    print(f"  ✗ Error posting {job['title'][:40]}: {e}")
        
        except ImportError:
            print("Note: wordpress-rest-client-pt not installed")
            print("To enable WordPress posting, run: pip install wordpress-rest-client-pt")

def main():
    """Main function"""
    scraper = JobScraper()
    
    # Run scraper
    scraper.scrape_all_sources()
    
    # Save to file
    scraper.save_to_json()
    
    # Optional: Post to WordPress (uncomment if needed)
    # scraper.post_to_wordpress(
    #     wp_url='https://bharatvacancy.com',
    #     wp_user='admin',
    #     wp_pass='your_password_here'
    # )
    
    print("\n✓ Scraper completed successfully!")

if __name__ == '__main__':
    main()
