'''
Updated scraper script to handle shadow DOM elements on nationalbanken.dk
'''
import os
import time
import json
import hashlib
import requests
import sys
from urllib.parse import urljoin, urlparse
from selenium.common.exceptions import TimeoutException
#from dlz_tools import DLZ
#dlz = DLZ()

print("Updating Chrome...")
if sys.platform.startswith("linux"):
    os.system("""
        apt-get update \
            && apt-get install -y \
            curl \
            gnupg \
            unzip \
            wget \
            jq \
            --no-install-recommends \
            && rm -rf /var/lib/apt/lists/*

        # Get the latest stable Chrome and ChromeDriver versions
        LATEST_STABLE_URL="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"

        # Download the JSON file and parse it for the linux64 chrome and chromedriver URLs
        CHROME_URL=$(curl -s $LATEST_STABLE_URL | jq -r '.channels.Stable.downloads.chrome[] | select(.platform=="linux64") | .url')
        CHROMEDRIVER_URL=$(curl -s $LATEST_STABLE_URL | jq -r '.channels.Stable.downloads.chromedriver[] | select(.platform=="linux64") | .url')

        # Download and unzip Chrome for Testing
        wget -O /tmp/chrome-linux64.zip $CHROME_URL \
            && unzip -o /tmp/chrome-linux64.zip -d /tmp/ \
            && mv /tmp/chrome-linux64/* /usr/bin/

        # Install dependencies for Chrome
        apt-get update && \
        while read -r pkg; do \
        apt-get satisfy -y --no-install-recommends "${pkg}"; \
        done < /usr/bin/deb.deps;

        # Download and unzip ChromeDriver
        wget -O /tmp/chromedriver-linux64.zip $CHROMEDRIVER_URL \
            && unzip -o /tmp/chromedriver-linux64.zip -d /tmp/ \
            && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ \
            && rm -rf /tmp/*
        """)

print("pip installing...")
#dlz.pip_install("selenium>=4.0.0")
#dlz.pip_install("webdriver-manager>=4.0.0")
#dlz.pip_install("requests>=2.32.3")


# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys

class NationalbankenScraper:
    """
    A scraper for downloading PDF documents from nationalbanken.dk.
    It handles shadow DOM, accepts cookies, and downloads files with metadata.
    """
    BASE_URL = "https://www.nationalbanken.dk"
    START_URL = "https://www.nationalbanken.dk/da/soeg-i-vidensarkivet"
    DOCS_DIR = "docs"
    METADATA_FILE = "docs_metadata.json"
    MAX_PAGES_TO_SCRAPE = 1

    def __init__(self, dlz_instance=None):
        """
        Initializes the scraper.

        Args:
            dlz_instance: An instance of the DLZ class for communication.
        """
        self.dlz = dlz_instance
        self.driver = None
        self.sent_files = set()
        self.all_metadata = []
        self.processed_article_urls = set()

    def __enter__(self):
        self.init_selenium_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_selenium_driver()
        self._save_final_metadata()

    def init_selenium_driver(self):
        """Initializes the Selenium WebDriver."""
        if self.driver is None:
            print("Initializing Selenium WebDriver...")
            try:
                chrome_options = ChromeOptions()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--window-size=1920,1080")
                
                # The following two lines are for local debugging, not for DLZ
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                
                # Use this for DLZ environment
                #self.driver = webdriver.Chrome(options=chrome_options)
                print("WebDriver initialized successfully.")
            except Exception as e:
                print(f"Error initializing WebDriver: {e}")
                self.driver = None
        return self.driver

    def close_selenium_driver(self):
        """Closes the Selenium WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            print("WebDriver closed.")

    def find_in_shadow_root(self, host_css_selector, shadow_css_selector):
        '''Find element within a shadow root using JavaScript execution.'''
        try:
            script = f"""
                const host = document.querySelector('{host_css_selector}');
                if (host && host.shadowRoot) {{
                    return host.shadowRoot.querySelector('{shadow_css_selector}');
                }}
                return null;
            """
            return self.driver.execute_script(script)
        except Exception as e:
            print(f"Error finding element in shadow root: {e}")
            return None

    def find_elements_in_all_shadow_roots(self, shadow_css_selector):
        '''Find elements in all shadow roots recursively using JavaScript.'''
        try:
            # Set a script timeout to prevent freezing
            self.driver.set_script_timeout(30)  # 30 seconds

            script = f'''
                const elements = [];
                const visited = new Set();

                function findInChildren(node) {{
                    if (!node || visited.has(node)) return;
                    visited.add(node);

                    // Search in the current node's shadow root
                    if (node.shadowRoot) {{
                        try {{
                            const found = node.shadowRoot.querySelectorAll(`{shadow_css_selector}`);
                            elements.push(...found);
                        }} catch (e) {{
                            console.error(`Error with selector in shadowRoot: {shadow_css_selector}`, e);
                        }}
                        // Important: also search inside the shadow root for more shadow hosts
                        findInChildren(node.shadowRoot);
                    }}

                    // Search for shadow hosts in the children of the current node (or shadow root)
                    const children = node.querySelectorAll('*');
                    for (const child of children) {{
                        if (child.shadowRoot) {{
                            findInChildren(child);
                        }}
                    }}
                }}

                findInChildren(document);
                return elements;
            '''
            elements = self.driver.execute_script(script)
            print(f"Found {len(elements)} elements in all shadow roots with selector: {shadow_css_selector}")
            return elements
        except TimeoutException:
            print(f"Timeout while searching for elements with selector: {shadow_css_selector}")
            return []
        except Exception as e:
            print(f"Error finding elements in shadow roots: {e}")
            return []

    def accept_cookies(self):
        '''Accepts cookies by clicking the "Allow all cookies" button if it's present.
        Handles both normal DOM and shadow DOM elements.'''
        try:
            print("Looking for cookie consent dialog...")
            
            # First check regular DOM
            try:
                # Wait for regular cookie dialog (shorter timeout)
                cookie_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
                )
                print("Cookie dialog found in regular DOM. Accepting cookies...")
                
                # Take screenshot before clicking
                self.driver.get_screenshot_as_file("before_cookie_click.png")
                
                # Try JavaScript click for reliability
                self.driver.execute_script("arguments[0].click();", cookie_button)
                print("Cookie accept button clicked.")

                # Wait for the dialog to disappear
                print("Waiting for cookie dialog to disappear...")
                WebDriverWait(self.driver, 10).until(
                    EC.invisibility_of_element_located((By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"))
                )
                print("Cookie dialog disappeared from regular DOM.")
                
            except Exception as dom_error:
                print(f"Cookie dialog not found in regular DOM: {dom_error}")
                #print("Checking for cookie dialog in shadow DOM...")
            
            # Wait for the page to stabilize before taking the screenshot
            time.sleep(1) 

            # Take a screenshot after clicking
            self.driver.get_screenshot_as_file("after_cookie_click.png")
            
            # Wait for dialog to disappear and page to stabilize
            time.sleep(2)
            return True
        
        except Exception as e:
            print(f"Error during cookie acceptance process: {e}")
            print("Continuing without accepting cookies.")
            return False

    def extract_attributes_from_shadow_element(self, element):
        '''Extract all attributes from a shadow DOM element'''
        try:
            attrs = self.driver.execute_script("""
                const attrs = {};
                for (const attr of arguments[0].attributes) {
                    attrs[attr.name] = attr.value;
                }
                return attrs;
            """, element)
            return attrs
        except Exception as e:
            print(f"Error extracting attributes: {e}")
            return {}

    def download_pdf(self, pdf_url, filename):
        '''Downloads a PDF from a URL to a local file, saves an MD5 file, and skips download if file with matching MD5 exists.'''
        if not os.path.exists(self.DOCS_DIR):
            os.makedirs(self.DOCS_DIR)

        safe_filename = "".join(
            c if c.isalnum() or c in ('.', '_', '-') else '_' 
            for c in os.path.basename(filename)
        )
        filepath = os.path.join(self.DOCS_DIR, safe_filename)
        md5_filepath = filepath + ".md5"

        def compute_md5(path):
            hash_md5 = hashlib.md5()
            try:
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                return hash_md5.hexdigest()
            except Exception as e:
                print(f"Error computing MD5 for {path}: {e}")
                return None

        # If file exists, check MD5
        if os.path.exists(filepath) and os.path.exists(md5_filepath):
            existing_md5 = compute_md5(filepath)
            try:
                with open(md5_filepath, "r", encoding="utf-8") as f:
                    saved_md5 = f.read().strip()
            except Exception as e:
                print(f"Error reading MD5 file {md5_filepath}: {e}")
                saved_md5 = None
            if existing_md5 and saved_md5 and existing_md5 == saved_md5:
                print(
                    f"File {safe_filename} already exists and MD5 matches. Skipping download."
                )
                self.sent_files.add(filepath)
                self.sent_files.add(md5_filepath)
                return existing_md5
            else:
                print(
                    f"File {safe_filename} exists but MD5 does not match or MD5 file missing. "
                    "Re-downloading."
                )

        try:
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/91.0.4472.124 Safari/537.36'
                )
            }
            response = requests.get(
                pdf_url, stream=True, timeout=30, headers=headers
            )
            response.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded {safe_filename}")
            # Compute and save MD5
            md5_hash = compute_md5(filepath)
            if md5_hash:
                with open(md5_filepath, "w", encoding="utf-8") as f:
                    f.write(md5_hash)
                print(f"MD5 hash saved to {md5_filepath}")
            self.sent_files.add(filepath)
            self.sent_files.add(md5_filepath)
            return md5_hash
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {pdf_url}: {e}")
            return None
        except IOError as e:
            print(f"Error writing file {filepath}: {e}")
            return None

    def analyze_shadow_dom_structure(self):
        '''Analyze the shadow DOM structure of the current page and print useful information'''
        print("\nAnalyzing shadow DOM structure of current page...")
        
        # Execute JavaScript to recursively inspect all shadow roots and return useful information
        structure = self.driver.execute_script(r"""
        // Track all shadow DOM roots
        const shadowRoots = [];
        
        // Find all shadow roots in the document
        function findShadowRoots(node, path) {
            if (!node) return;
            
            if (node.querySelectorAll) {
                const elements = node.querySelectorAll('*');
                for (const el of elements) {
                    if (el.shadowRoot) {
                        const nodePath = path + ' > ' + (el.tagName || 'unknown').toLowerCase() + 
                            (el.id ? '#' + el.id : '') + 
                            (el.className && typeof el.className === 'string' ? '.' + el.className.replace(/\s+/g, '.') : '');
                        
                        // Gather info about this shadow root
                        const info = {
                            hostTagName: el.tagName,
                            hostId: el.id || null,
                            hostClass: el.className || null,
                            path: nodePath,
                            childElements: {}
                        };
                        
                        // Look for interesting elements inside this shadow root
                        const links = el.shadowRoot.querySelectorAll('a');
                        if (links.length) {
                            info.links = Array.from(links).slice(0, 5).map(a => ({
                                href: a.href || null,
                                text: a.textContent || null,
                                download: a.hasAttribute('download'),
                                class: a.className || null
                            }));
                        }
                        
                        // Count element types in this shadow root
                        Array.from(el.shadowRoot.querySelectorAll('*')).forEach(child => {
                            const tag = child.tagName.toLowerCase();
                            info.childElements[tag] = (info.childElements[tag] || 0) + 1;
                        });
                        
                        shadowRoots.push(info);
                        
                        // Recursively check for nested shadow roots
                        findShadowRoots(el.shadowRoot, nodePath);
                    }
                }
            }
        }
        
        findShadowRoots(document, 'document');
        
        // Also specifically look for PDF links in all shadow roots
        const pdfLinks = [];
        
        function findPdfLinksInShadows(rootNode) {
            if (!rootNode || !rootNode.querySelectorAll) return;
            
            // Check all elements for shadow roots
            const elements = rootNode.querySelectorAll('*');
            for (const el of elements) {
                if (el.shadowRoot) {
                    // Look for links in this shadow root
                    const links = el.shadowRoot.querySelectorAll('a');
                    for (const link of links) {
                        const href = link.href || link.getAttribute('href') || '';
                        if (href.toLowerCase().endsWith('.pdf') || link.hasAttribute('download')) {
                            pdfLinks.push({
                                href: href,
                                text: link.textContent || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostTag: el.tagName.toLowerCase(),
                                hostPath: el.id ? '#' + el.id : el.className ? '.' + el.className.replace(/\s+/g, '.') : el.tagName.toLowerCase()
                            });
                        }
                    }
                    
                    // Recursively check nested shadow roots
                    findPdfLinksInShadows(el.shadowRoot);
                }
            }
        }
        
        findPdfLinksInShadows(document);
        
        return {
            shadowRoots: shadowRoots,
            pdfLinks: pdfLinks,
            totalShadowRoots: shadowRoots.length
        };
    """)
        
        print(f"\nFound {structure.get('totalShadowRoots', 0)} shadow roots on page")
        
        # Print PDF links specifically
        pdf_links = structure.get('pdfLinks', [])
        print(f"Found {len(pdf_links)} potential PDF links in shadow DOM:")
        for i, link in enumerate(pdf_links[:5]):  # Show first 5 only
            print(f"  Link {i+1}:")
            print(f"    href: {link.get('href', 'N/A')}")
            print(f"    text: {link.get('text', 'N/A')}")
            print(f"    download attr: {link.get('hasDownload', False)}")
            print(f"    class: {link.get('class', 'N/A')}")
            print(f"    host: {link.get('hostTag', 'N/A')} ({link.get('hostPath', 'N/A')})")
        
        # Print some shadow roots
        shadow_roots = structure.get('shadowRoots', [])
        print(f"\nShowing details for first few shadow roots:")
        for i, root in enumerate(shadow_roots[:3]):  # Show first 3 only
            print(f"  Root {i+1}: {root.get('hostTagName', 'unknown')} - {root.get('path', 'unknown path')}")
            print(f"    Child elements: {root.get('childElements', {})}")
            if 'links' in root:
                print(f"    Contains {len(root['links'])} links")
                
        return structure

    def extract_pdf_links_from_shadow_dom(self):
        '''Extract all PDF links from shadow DOM using specialized JavaScript.
        Returns a list of dictionaries with href and other properties.'''
        print("Extracting PDF links from shadow DOM with specialized JavaScript...")
        
        script = r"""
        // Track all PDF links
        const pdfLinks = [];
        
        // Common PDF link patterns
        const PDF_SELECTORS = [
            'a.related-card__link[download]',
            'a.related-card__link[href$=".pdf"]',
            'a[download]',
            'a[href$=".pdf"]',
            'a[href*=".pdf"]',
            'a.download-file',
            'a.pdf-link'
        ];
        
        // Search document and all shadow roots recursively
        function findPdfLinks(node, path) {
            if (!node || !node.querySelectorAll) return;
            
            // Check regular links in this node
            PDF_SELECTORS.forEach(selector => {
                try {
                    const links = node.querySelectorAll(selector);
                    for (const link of links) {
                        const href = link.href || link.getAttribute('href') || '';
                        if (href.toLowerCase().includes('.pdf') || link.hasAttribute('download')) {
                            pdfLinks.push({
                                href: href,
                                text: link.textContent?.trim() || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostPath: path
                            });
                        }
                    }
                } catch (e) {
                    console.error('Error searching for selector:', selector, e);
                }
            });
            
            // Check for shadow roots
            if (node.querySelectorAll) {
                const elements = node.querySelectorAll('*');
                for (const el of elements) {
                    if (el.shadowRoot) {
                        const nodePath = path + ' > ' + (el.tagName || 'unknown').toLowerCase() + 
                            (el.id ? '#' + el.id : '') + 
                            (el.className && typeof el.className === 'string' ? '.' + el.className.replace(/\s+/g, '.') : '');
                        
                        // Search inside this shadow root
                        findPdfLinks(el.shadowRoot, nodePath);
                    }
                }
            }
        }
        
        // Start searching from the document
        findPdfLinks(document, 'document');
        
        // Look specifically for related card links which might be special components
        document.querySelectorAll('*').forEach(el => {
            if (el.shadowRoot) {
                const relatedCards = el.shadowRoot.querySelectorAll('*[class*="related-card"]');
                if (relatedCards.length) {
                    relatedCards.forEach(card => {
                        // Try to find links inside related cards
                        const links = card.querySelectorAll('a');
                        links.forEach(link => {
                            const href = link.href || link.getAttribute('href') || '';
                            pdfLinks.push({
                                href: href,
                                text: link.textContent?.trim() || null,
                                hasDownload: link.hasAttribute('download'),
                                class: link.className || null,
                                hostPath: 'related-card'
                            });
                        });
                    });
                }
            }
        });
        
        return pdfLinks;
    """
        
        links = self.driver.execute_script(script)
        print(f"Found {len(links)} potential PDF links in shadow DOM.")
        
        # Filter to keep only actual PDF links
        pdf_links = [link for link in links if link['href'] and 
                    ('.pdf' in link['href'].lower() or link.get('hasDownload'))]
        
        print(f"After filtering: {len(pdf_links)} PDF links.")
        return pdf_links

    def extract_pdf_links_from_custom_elements(self):
        script = '''
            // Find all elements with a 'link' attribute (e.g., dnb-related-card)
            let results = [];
            function extractFromNode(node) {
                if (!node || !node.querySelectorAll) return;
                const all = node.querySelectorAll('[link]');
                for (const el of all) {
                    let linkAttr = el.getAttribute('link');
                    if (linkAttr) {
                        try {
                            let linkObj = JSON.parse(linkAttr);
                            if (linkObj && linkObj.url && linkObj.url.toLowerCase().endsWith('.pdf')) {
                                results.push({
                                    href: linkObj.url,
                                    text: el.getAttribute('name') || el.getAttribute('header') || null,
                                    hostTag: el.tagName
                                });
                            }
                        } catch (e) {}
                    }
                }
                // Search shadow roots recursively
                const elements = node.querySelectorAll('*');
                for (const el of elements) {
                    if (el.shadowRoot) {
                        extractFromNode(el.shadowRoot);
                    }
                }
            }
            extractFromNode(document);
            return results;
        '''
        return self.driver.execute_script(script)

    def save_metadata_per_page(self, metadata, page_num):
        '''Saves the current metadata to a JSON file with page number in the filename'''
        if not metadata:
            print(f"No metadata to save for page {page_num}")
            return
            
        if not os.path.exists(self.DOCS_DIR):
            os.makedirs(self.DOCS_DIR)
            
        metadata_filename = os.path.join(self.DOCS_DIR, f"metadata_page_{page_num}.json")
        
        try:
            with open(metadata_filename, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False)
            print(f"Metadata for page {page_num} saved to {metadata_filename}")
            self.sent_files.add(metadata_filename)
        except Exception as e:
            print(f"Error saving metadata for page {page_num}: {e}")

    def _save_final_metadata(self):
        """Saves the aggregated metadata to the main metadata file."""
        if self.all_metadata:
            print(
                "Metadata for {} PDFs saved to {}".format(
                    len(self.all_metadata), self.METADATA_FILE
                )
            )
            with open(self.METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.all_metadata, f, indent=4, ensure_ascii=False)
            self.sent_files.add(self.METADATA_FILE)
        else:
            print("No PDFs were downloaded, so no metadata file created.")

    def run(self):
        """
        Main method to run the scraper.
        
        Returns:
            A list of file paths for all created files.
        """
        if not os.path.exists(self.DOCS_DIR):
            os.makedirs(self.DOCS_DIR)

        page_num = 1
        first_page = True

        try:
            if not self.driver:
                print("WebDriver not initialized. Exiting.")
                return []
                
            while True:
                if page_num > self.MAX_PAGES_TO_SCRAPE:
                    print(f"Reached max page limit ({self.MAX_PAGES_TO_SCRAPE}), stopping.")
                    break

                current_search_url = f"{self.START_URL}?page={page_num}" if page_num > 1 else self.START_URL
                print(f"Processing search page: {current_search_url}")
                
                # Load the search page
                self.driver.get(current_search_url)
                time.sleep(3)
                
                # Accept cookies if needed
                if page_num == 1 or first_page:
                    self.accept_cookies()
                
                # Find search result items in shadow DOM
                result_items = self.find_elements_in_all_shadow_roots("dnb-search-result-item")
                
                if not result_items:
                    if page_num == 1:
                        print("No search results found on the first page. Exiting.")
                    else:
                        print("No more search results found. End of results.")
                    break
                print(f"Found {len(result_items)} search result items on page {page_num}")
                
                # First, extract all article data and URLs from the search page
                page_articles = []
                found_new_articles_on_page = False
                
                # Store the metadata for each page separately
                page_metadata = []
                
                print("Extracting article metadata from search results...")
                for item in result_items:
                    # Extract attributes from the shadow DOM element
                    attrs = self.extract_attributes_from_shadow_element(item)
                    
                    # Get article information
                    article_title = attrs.get('header', 'N/A').strip()
                    content_type = attrs.get('content-type', '')
                    topic = attrs.get('topic', '')
                    date = attrs.get('date', '')
                    description = attrs.get('description', '')
                    
                    # Extract URL from link attribute (which is a JSON string)
                    link_json_str = attrs.get('link', '{}')
                    article_url = None
                    
                    try:
                        link_data = json.loads(link_json_str)
                        raw_url = link_data.get('url')
                        if (raw_url):
                            article_url = urljoin(self.BASE_URL, raw_url)
                    except json.JSONDecodeError:
                        print(f"  Error decoding link JSON for item '{article_title}': {link_json_str}")
                    
                    # If no URL found, skip this item
                    if not article_url:
                        print(f"Could not find a valid URL for item: {article_title}")
                        continue
                    
                    # Skip if already processed
                    if article_url in self.processed_article_urls:
                        print(f"  Skipping already processed article: {article_title}")
                        continue
                    
                    # Store the article metadata for later processing
                    page_articles.append({
                        'url': article_url,
                        'title': article_title,
                        'content_type': content_type,
                        'topic': topic,
                        'date': date,
                        'description': description
                    })
                    found_new_articles_on_page = True

                print(f"Articles found on page: {[a['url'] for a in page_articles]}")

                # Now visit each article URL one by one
                for article in page_articles:
                    article_url = article['url']
                    article_title = article['title']
                    
                    self.processed_article_urls.add(article_url)
                    print(f"  Visiting article page: {article_title} ({article_url})")
                    # Load the article page
                    self.driver.get(article_url)

                    WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, "h2"))
                    )
                    time.sleep(2)  # Wait for page to load
                    
                    # Analyze the shadow DOM structure to better understand the page
                    shadow_structure = self.analyze_shadow_dom_structure()
                    
                    # First try to use the PDF links we found from our shadow DOM analysis
                    pdf_links = []
                    pdf_links_from_analysis = shadow_structure.get('pdfLinks', [])
                    
                    if pdf_links_from_analysis:
                        #print(f"Found {len(pdf_links_from_analysis)} PDF links from shadow DOM analysis")
                        
                        # Convert the analyzed links to objects that can be used like WebElements
                        for link_info in pdf_links_from_analysis:
                            href = link_info.get('href')
                            if href and (href.lower().endswith('.pdf') or link_info.get('hasDownload')):
                                # Create a dictionary that mimics a WebElement with properties we need
                                link_obj = {
                                    'href': href,
                                    'text': link_info.get('text'),
                                    'getAttribute': lambda attr, h=href: h if attr == 'href' else None
                                }
                                pdf_links.append(link_obj)
                    
                    # If no PDF links found through analysis, try regular DOM
                    if not pdf_links:
                        regular_pdf_links = self.driver.find_elements(By.CSS_SELECTOR, "a.related-card__link[download], a[href$='.pdf']")
                        
                        if regular_pdf_links:
                            pdf_links = regular_pdf_links
                        else:
                            # If still nothing found, try our custom shadow DOM search
                            shadow_selectors = [
                                "a.related-card__link[download]",
                                "a.related-card__link[href$='.pdf']",
                                "a[download]", 
                                "a[href$='.pdf']",
                                "a[href*='.pdf']"
                            ]
                            
                            for selector in shadow_selectors:
                                pdf_links_in_shadow = self.find_elements_in_all_shadow_roots(selector)
                                if pdf_links_in_shadow:
                                    pdf_links = pdf_links_in_shadow
                                    break
                    
                    custom_pdf_links = self.extract_pdf_links_from_custom_elements()
                    
                    all_pdf_links = []
                    if pdf_links:
                        all_pdf_links.extend(pdf_links)
                    if custom_pdf_links:
                        for link in custom_pdf_links:
                            href = link.get('href')
                            if href and not any((isinstance(l, dict) and l.get('href') == href) or (hasattr(l, 'get_attribute') and l.get_attribute('href') == href) for l in all_pdf_links):
                                all_pdf_links.append(link)

                    print(f"Found {len(all_pdf_links)} total potential PDF links")

                    pdf_found_for_article = False
                    for pdf_link in all_pdf_links:
                        try:
                            pdf_href = None
                            if isinstance(pdf_link, dict) and 'href' in pdf_link:
                                pdf_href = pdf_link['href']
                                print(f"Processing PDF link: {pdf_href}")
                            elif hasattr(pdf_link, 'get_attribute'):
                                pdf_href = pdf_link.get_attribute('href')
                                if not pdf_href:
                                    pdf_href = self.driver.execute_script("return arguments[0].href || arguments[0].getAttribute('href');", pdf_link)
                            else:
                                try:
                                    pdf_href = self.driver.execute_script("return arguments[0].href || arguments[0].getAttribute('href');", pdf_link)
                                except Exception:
                                    print(f"    Cannot extract href from {type(pdf_link)}")
                            if pdf_href and pdf_href.lower().endswith(".pdf"):
                                full_pdf_url = urljoin(self.BASE_URL, pdf_href)
                                parsed_pdf_url = urlparse(full_pdf_url)
                                pdf_filename = os.path.basename(parsed_pdf_url.path)
                                if not pdf_filename:
                                    print(f"Could not determine filename for PDF: {full_pdf_url}")
                                    continue
                                print(f"Found PDF: {full_pdf_url}")
                                md5_hash = self.download_pdf(full_pdf_url, pdf_filename)
                                if md5_hash:
                                    metadata = {
                                        "source_page_url": article_url,
                                        "pdf_url": full_pdf_url,
                                        "downloaded_filename": pdf_filename,
                                        "title": article['title'],
                                        "date": article['date'],
                                        "content_type": article['content_type'],
                                        "topic": article['topic'],
                                        "description": article['description'],
                                        "file_md5": md5_hash
                                    }
                                    self.all_metadata.append(metadata)
                                    page_metadata.append(metadata)
                                    pdf_found_for_article = True
                                else:
                                    print(f"    Failed to download {pdf_filename}")
                        except Exception as e:
                            print(f"Error processing PDF link: {e}")
                    if not pdf_found_for_article:
                        print(
                            "No PDF download link found on article page: "
                            f"{article_url}"
                        )
                
                self.save_metadata_per_page(page_metadata, page_num)
                
                if not found_new_articles_on_page and page_num > 1:
                    print(
                        "No new articles found on this page, stopping pagination."
                    )
                    break
                
                page_num += 1
                first_page = False

        except KeyboardInterrupt:
            print("\nScraping interrupted by user.")
        except Exception as e:
            print(f"Unexpected error: {e}")
        finally:
            print(
                "Browser window left open for inspection. "
                "Close it manually when done."
            )
            return list(self.sent_files)


def main():
    """Main function to run the scraper."""
    with NationalbankenScraper() as scraper:
        files_to_send = scraper.run()

    if files_to_send:
        for fpath in files_to_send:
            pass
            #print(f"Sending file {fpath}")
            #dlz.send_file_created(fpath)

if __name__ == "__main__":
    main()

