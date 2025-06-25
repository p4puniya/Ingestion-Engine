import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urljoin, urlparse, parse_qs
from typing import List, Dict, Set, Optional
import time
import random

class ContentDiscovery:
    """
    Generic content discovery system that finds JavaScript-loaded content,
    API endpoints, pagination links, and category pages without being
    tied to specific websites.
    """
    
    def __init__(self, base_url: str, max_depth: int = 3, delay: float = 1.0):
        self.base_url = base_url
        self.max_depth = max_depth
        self.delay = delay
        self.visited = set()
        self.discovered_urls = set()
        self.api_endpoints = set()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def discover_all_content(self) -> Dict[str, Set[str]]:
        """
        Main discovery method that finds all types of content.
        Returns a dictionary with different types of discovered URLs.
        """
        print(f"[DISCOVERY] Starting content discovery for {self.base_url}")
        
        # Start with the base URL
        self._discover_from_page(self.base_url, depth=0)
        
        # Look for common patterns and API endpoints
        self._find_api_endpoints()
        self._find_sitemaps()
        self._find_rss_feeds()
        
        return {
            'content_urls': self.discovered_urls,
            'api_endpoints': self.api_endpoints,
            'pagination_urls': self._find_pagination_patterns(),
            'category_urls': self._find_category_patterns()
        }
    
    def _discover_from_page(self, url: str, depth: int):
        """Recursively discover content from a page."""
        if depth > self.max_depth or url in self.visited:
            return
        
        self.visited.add(url)
        print(f"[DISCOVERY] Exploring {url} (depth {depth})")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            html_content = response.text
            
            # Find all links on the page
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract links
            links = self._extract_links(soup, url)
            
            # Look for JavaScript patterns that might indicate dynamic content
            js_patterns = self._find_js_content_patterns(html_content)
            
            # Look for API calls in JavaScript
            api_calls = self._find_api_calls_in_js(html_content)
            
            # Add discovered URLs
            self.discovered_urls.update(links)
            self.api_endpoints.update(api_calls)
            
            # Add delay to be respectful
            time.sleep(self.delay + random.uniform(0, 0.5))
            
            # Recursively explore if within depth limit
            if depth < self.max_depth:
                for link in links:
                    if self._should_explore_link(link):
                        self._discover_from_page(link, depth + 1)
                        
        except Exception as e:
            print(f"[DISCOVERY] Error exploring {url}: {e}")
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extract all links from a page."""
        links = set()
        
        # Standard anchor tags
        for a in soup.find_all('a', href=True):
            href = a['href']
            abs_url = urljoin(base_url, href)
            if self._is_valid_url(abs_url):
                links.add(abs_url)
        
        # Look for links in data attributes (common in JS frameworks)
        for element in soup.find_all(attrs={'data-href': True}):
            href = element.get('data-href')
            abs_url = urljoin(base_url, href)
            if self._is_valid_url(abs_url):
                links.add(abs_url)
        
        # Look for links in onclick handlers
        for element in soup.find_all(attrs={'onclick': True}):
            onclick = element.get('onclick', '')
            urls = re.findall(r'["\']([^"\']*\.html?[^"\']*)["\']', onclick)
            for url in urls:
                abs_url = urljoin(base_url, url)
                if self._is_valid_url(abs_url):
                    links.add(abs_url)
        
        return links
    
    def _find_js_content_patterns(self, html_content: str) -> Set[str]:
        """Find patterns that indicate JavaScript-loaded content."""
        patterns = set()
        
        # Look for common JS framework patterns
        js_patterns = [
            r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
            r'router\.push\(["\']([^"\']+)["\']',
            r'navigate\(["\']([^"\']+)["\']',
            r'history\.pushState\([^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']',
            r'fetch\(["\']([^"\']+)["\']',
            r'axios\.get\(["\']([^"\']+)["\']',
            r'\.ajax\([^)]*url:\s*["\']([^"\']+)["\']',
        ]
        
        for pattern in js_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                abs_url = urljoin(self.base_url, match)
                if self._is_valid_url(abs_url):
                    patterns.add(abs_url)
        
        return patterns
    
    def _find_api_calls_in_js(self, html_content: str) -> Set[str]:
        """Find API endpoints called from JavaScript."""
        api_endpoints = set()
        
        # Common API patterns
        api_patterns = [
            r'["\'](/api/[^"\']+)["\']',
            r'["\'](/wp-json/[^"\']+)["\']',  # WordPress
            r'["\'](/ghost/api/[^"\']+)["\']',  # Ghost
            r'["\'](/graphql[^"\']*)["\']',  # GraphQL
            r'["\'](/rest/[^"\']+)["\']',  # REST APIs
            r'["\'](/v\d+/[^"\']+)["\']',  # Versioned APIs
        ]
        
        for pattern in api_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            for match in matches:
                abs_url = urljoin(self.base_url, match)
                if self._is_valid_url(abs_url):
                    api_endpoints.add(abs_url)
        
        return api_endpoints
    
    def _find_api_endpoints(self):
        """Try to discover API endpoints by checking common paths."""
        common_api_paths = [
            '/api',
            '/api/posts',
            '/api/blog',
            '/api/articles',
            '/wp-json/wp/v2/posts',
            '/ghost/api/content/posts',
            '/graphql',
            '/rest',
            '/v1',
            '/v2',
        ]
        
        for path in common_api_paths:
            try:
                url = urljoin(self.base_url, path)
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    self.api_endpoints.add(url)
                    print(f"[DISCOVERY] Found API endpoint: {url}")
            except:
                continue
    
    def _find_sitemaps(self):
        """Find and parse sitemaps."""
        sitemap_paths = [
            '/sitemap.xml',
            '/sitemap_index.xml',
            '/sitemap-posts.xml',
            '/sitemap-blog.xml',
            '/robots.txt'
        ]
        
        for path in sitemap_paths:
            try:
                url = urljoin(self.base_url, path)
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    if path == '/robots.txt':
                        # Extract sitemap URLs from robots.txt
                        sitemap_urls = re.findall(r'Sitemap:\s*(.+)', response.text, re.IGNORECASE)
                        for sitemap_url in sitemap_urls:
                            self._parse_sitemap(sitemap_url.strip())
                    else:
                        self._parse_sitemap(url)
            except:
                continue
    
    def _parse_sitemap(self, sitemap_url: str):
        """Parse a sitemap XML file."""
        try:
            response = requests.get(sitemap_url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.content, 'xml')
            
            # Find all URLs in sitemap
            for loc in soup.find_all('loc'):
                url = loc.get_text()
                if self._is_valid_url(url):
                    self.discovered_urls.add(url)
            
            # Look for sitemap index files
            for sitemap in soup.find_all('sitemap'):
                sitemap_url = sitemap.find('loc').get_text()
                self._parse_sitemap(sitemap_url)
                
        except Exception as e:
            print(f"[DISCOVERY] Error parsing sitemap {sitemap_url}: {e}")
    
    def _find_rss_feeds(self):
        """Find RSS/Atom feeds."""
        feed_paths = [
            '/feed',
            '/rss',
            '/rss.xml',
            '/feed.xml',
            '/atom.xml',
            '/blog/feed',
            '/blog/rss'
        ]
        
        for path in feed_paths:
            try:
                url = urljoin(self.base_url, path)
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    self._parse_feed(url, response.text)
            except:
                continue
    
    def _parse_feed(self, feed_url: str, content: str):
        """Parse RSS/Atom feeds."""
        try:
            soup = BeautifulSoup(content, 'xml')
            
            # RSS feeds
            for item in soup.find_all('item'):
                link = item.find('link')
                if link:
                    url = link.get_text()
                    if self._is_valid_url(url):
                        self.discovered_urls.add(url)
            
            # Atom feeds
            for entry in soup.find_all('entry'):
                link = entry.find('link')
                if link and link.get('href'):
                    url = link.get('href')
                    if self._is_valid_url(url):
                        self.discovered_urls.add(url)
                        
        except Exception as e:
            print(f"[DISCOVERY] Error parsing feed {feed_url}: {e}")
    
    def _find_pagination_patterns(self) -> Set[str]:
        """Find pagination URLs from discovered URLs."""
        pagination_urls = set()
        
        # Common pagination patterns
        pagination_patterns = [
            r'page=\d+',
            r'p=\d+',
            r'paged=\d+',
            r'/page/\d+',
            r'/p/\d+',
            r'/posts/\d+',
            r'/blog/\d+',
        ]
        
        for url in self.discovered_urls:
            for pattern in pagination_patterns:
                if re.search(pattern, url):
                    # Generate more pages
                    base_url = re.sub(pattern, '', url)
                    for page in range(1, 11):  # Try first 10 pages
                        if 'page=' in pattern:
                            pagination_urls.add(f"{base_url}page={page}")
                        elif 'p=' in pattern:
                            pagination_urls.add(f"{base_url}p={page}")
                        elif 'paged=' in pattern:
                            pagination_urls.add(f"{base_url}paged={page}")
                        elif '/page/' in pattern:
                            pagination_urls.add(f"{base_url}/page/{page}")
                        elif '/p/' in pattern:
                            pagination_urls.add(f"{base_url}/p/{page}")
        
        return pagination_urls
    
    def _find_category_patterns(self) -> Set[str]:
        """Find category/tag URLs from discovered URLs."""
        category_urls = set()
        
        # Common category patterns
        category_patterns = [
            r'/category/',
            r'/tag/',
            r'/topic/',
            r'/section/',
            r'/blog/category/',
            r'/blog/tag/',
        ]
        
        for url in self.discovered_urls:
            for pattern in category_patterns:
                if pattern in url:
                    category_urls.add(url)
                    # Try to find more category pages
                    base_url = url.split(pattern)[0] + pattern
                    category_urls.add(base_url)
        
        return category_urls
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and should be explored."""
        if not url:
            return False
        
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return False
            
            # Only explore same domain
            base_domain = urlparse(self.base_url).netloc
            if parsed.netloc != base_domain:
                return False
            
            # Skip common non-content URLs
            skip_patterns = [
                r'\.(css|js|png|jpg|jpeg|gif|svg|ico|pdf|zip|tar|gz)$',
                r'#',
                r'mailto:',
                r'tel:',
                r'javascript:',
                r'/admin/',
                r'/login',
                r'/logout',
                r'/wp-admin/',
            ]
            
            for pattern in skip_patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return False
            
            return True
        except:
            return False
    
    def _should_explore_link(self, url: str) -> bool:
        """Determine if a link should be explored further."""
        # Skip if already visited
        if url in self.visited:
            return False
        
        # Skip if it's likely an API endpoint
        if '/api/' in url or '/wp-json/' in url:
            return False
        
        # Skip if it's a file download
        if any(ext in url.lower() for ext in ['.pdf', '.zip', '.doc', '.xls']):
            return False
        
        return True


def discover_content_from_url(base_url: str, max_depth: int = 3) -> Dict[str, Set[str]]:
    """
    Convenience function to discover content from a URL.
    
    Args:
        base_url: The starting URL for discovery
        max_depth: Maximum depth to crawl
    
    Returns:
        Dictionary containing discovered URLs by type
    """
    discovery = ContentDiscovery(base_url, max_depth=max_depth)
    return discovery.discover_all_content()


def enhance_crawl_with_discovery(start_url: str, depth: int, visited: set = None) -> List[tuple]:
    """
    Enhanced crawling function that combines your existing crawl logic
    with the new discovery capabilities.
    
    This function can be used as a drop-in replacement for your existing
    crawl_urls function to get more comprehensive results.
    """
    if visited is None:
        visited = set()
    
    # Use the discovery system to find additional URLs
    discovery_results = discover_content_from_url(start_url, max_depth=depth)
    
    # Combine all discovered URLs
    all_urls = set()
    all_urls.update(discovery_results['content_urls'])
    all_urls.update(discovery_results['pagination_urls'])
    all_urls.update(discovery_results['category_urls'])
    
    # Convert to the format your existing system expects
    results = []
    for url in all_urls:
        if url not in visited:
            try:
                response = requests.get(url, timeout=15)
                response.raise_for_status()
                html = response.text
                results.append((url, html, set()))  # Empty set for found_urls to maintain compatibility
                visited.add(url)
            except Exception as e:
                print(f"[ENHANCED_CRAWL] Failed to fetch {url}: {e}")
    
    return results 