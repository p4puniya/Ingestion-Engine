import { useState, useEffect } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import './App.css';

const API_URL = 'http://localhost:8000'; // Change if backend runs elsewhere

type OutputItem = {
  title: string;
  content: string;
  content_type: string;
  source_url: string;
  author: string;
  user_id: string;
  author_method?: string; // Method used to extract author (openai/fallback)
};

type OutputJSON = {
  team_id: string;
  items: OutputItem[];
};

type UrlData = {
  original_url: string;
  depth_level: number;
  found_urls: string[];
};

type ApiResponse = {
  status: string;
  processed_output?: OutputJSON;
  raw_output?: any;
  urls?: UrlData[];
  message?: string;
  processing_log?: string[]; // Processing progress messages
  total_files_processed?: number;
  total_items_extracted?: number;
  // Keep backward compatibility
  output?: OutputJSON;
  items?: OutputItem[];
  team_id: string;
  task_id?: string;
};

function App() {
  // Add CSS animations
  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }
    `;
    document.head.appendChild(style);
    return () => {
      if (document.head.contains(style)) {
        document.head.removeChild(style);
      }
    };
  }, []);

  // State variables
  const [teamId, setTeamId] = useState('aline123');
  const [userId, setUserId] = useState('');
  const [depth, setDepth] = useState(0);
  const [urls, setUrls] = useState('');
  const [pdfs, setPdfs] = useState<FileList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [output, setOutput] = useState<OutputJSON | null>(null);
  const [rawOutput, setRawOutput] = useState<any>(null);
  const [showRawOutput, setShowRawOutput] = useState(false);
  const [urlsData, setUrlsData] = useState<UrlData[]>([]);
  const [selectedUrls, setSelectedUrls] = useState<{ [url: string]: boolean }>({});
  const [lastCrawledDepth, setLastCrawledDepth] = useState<number | null>(null);
  const [authorMode, setAuthorMode] = useState<'cost_saving' | 'balanced' | 'accuracy'>('balanced');

  const handleTeamIdChange = (e: ChangeEvent<HTMLInputElement>) => setTeamId(e.target.value);
  const handleUserIdChange = (e: ChangeEvent<HTMLInputElement>) => setUserId(e.target.value);
  const handleDepthChange = (e: ChangeEvent<HTMLSelectElement>) => setDepth(Number(e.target.value));
  const handleUrlsChange = (e: ChangeEvent<HTMLTextAreaElement>) => setUrls(e.target.value);
  const handleAuthorModeChange = (e: ChangeEvent<HTMLSelectElement>) => setAuthorMode(e.target.value as 'cost_saving' | 'balanced' | 'accuracy');
  const handlePdfsChange = (e: ChangeEvent<HTMLInputElement>) => {
    const newFiles = e.target.files;
    if (!newFiles || newFiles.length === 0) return;
    
    // If no existing files, just set the new files
    if (!pdfs) {
      setPdfs(newFiles);
      return;
    }
    
    // Append new files to existing files
    const dataTransfer = new DataTransfer();
    
    // Add existing files
    Array.from(pdfs).forEach(file => dataTransfer.items.add(file));
    
    // Add new files
    Array.from(newFiles).forEach(file => dataTransfer.items.add(file));
    
    setPdfs(dataTransfer.files);
    
    // Clear the input value so the same file can be selected again
    e.target.value = '';
  };

  const handleClearAllPdfs = () => {
    setPdfs(null);
  };

  const handleRemovePdf = (index: number) => {
    if (!pdfs) return;
    const newFiles = Array.from(pdfs).filter((_, i) => i !== index);
    // Create a new FileList from the filtered array
    const dataTransfer = new DataTransfer();
    newFiles.forEach(file => dataTransfer.items.add(file));
    setPdfs(dataTransfer.files);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    
    setLoading(true);
    
    if (!teamId.trim()) {
      alert('Please enter a Team ID');
      setLoading(false);
      return;
    }

    const formData = new FormData();
    formData.append('team_id', teamId);
    formData.append('user_id', userId);
    formData.append('author_mode', authorMode);

    // Add URLs
    if (urls.trim()) {
      const urlList = urls.split('\n').filter(url => url.trim());
      urlList.forEach(url => formData.append('urls', url.trim()));
    }

    // Add PDFs
    if (pdfs && pdfs.length > 0) {
      Array.from(pdfs).forEach(pdf => {
        formData.append('pdfs', pdf);
      });
    }

    try {
      const response = await fetch(`${API_URL}/ingest/batch`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      
      setOutput(result);
      setLoading(false);
    } catch (error) {
      console.error('Error:', error);
      setError(error instanceof Error ? error.message : 'An error occurred');
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!output) return;
    const blob = new Blob([JSON.stringify(output, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ingestion_output.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const handleDownloadRaw = () => {
    if (!rawOutput) return;
    const blob = new Blob([JSON.stringify(rawOutput, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `raw_ingestion_output.json`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  const handleDownloadMarkdown = () => {
    if (!output) return;
    
    // Convert the processed output to markdown format
    let markdownContent = `# Knowledge Ingestion Output\n\n`;
    markdownContent += `**Team ID:** ${output.team_id}\n\n`;
    
    output.items?.forEach((item, index) => {
      markdownContent += `## ${item.title || `Item ${index + 1}`}\n\n`;
      if (item.source_url && item.source_url.startsWith('http')) {
        markdownContent += `**Source:** [${item.source_url}](${item.source_url})\n`;
      } else {
        markdownContent += `**Source:** ${item.source_url}\n`;
      }
      markdownContent += `**Author:** ${item.author || 'Unknown'}`;
      if (item.author_method) {
        markdownContent += ` (${item.author_method === 'openai' ? 'OpenAI' : 'Manual'})`;
      }
      markdownContent += `\n`;
      markdownContent += `**User ID:** ${item.user_id}\n`;
      markdownContent += `**Content Type:** ${item.content_type}\n\n`;
      markdownContent += `${item.content}\n\n`;
      markdownContent += `---\n\n`;
    });
    
    const blob = new Blob([markdownContent], { type: 'text/markdown' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `formatted_content.md`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  useEffect(() => {
    if (urlsData.length > 0) {
      const allUrls: string[] = urlsData.flatMap(u => u.found_urls);
      const initial: { [url: string]: boolean } = {};
      allUrls.forEach(url => { initial[url] = true; });
      setSelectedUrls(initial);
      setLastCrawledDepth(urlsData[urlsData.length - 1].depth_level);
    }
  }, [urlsData]);

  const handleUrlCheckbox = (url: string) => {
    setSelectedUrls(prev => ({ ...prev, [url]: !prev[url] }));
  };

  const handleContinueToNextDepth = async () => {
    setError('');
    setOutput(null);
    setRawOutput(null);
    setLoading(true);
    try {
      // Only allow if we have a single root URL (not batch)
      const rootUrl = urls.trim().split('\n').filter(Boolean)[0];
      if (!rootUrl) {
        setError('No URL found to continue crawling.');
        setLoading(false);
        return;
      }
      const excludeUrls = Object.entries(selectedUrls)
        .filter(([_, checked]) => !checked)
        .map(([url]) => url);
      const nextDepth = (lastCrawledDepth ?? 0) + 1;
      const response = await fetch(`${API_URL}/ingest/url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: rootUrl,
          team_id: teamId,
          user_id: userId,
          depth: nextDepth,
          exclude_urls: excludeUrls,
          _t: Date.now(),
        }),
      });
      if (!response.ok) throw new Error('Ingestion failed.');
      const data: ApiResponse = await response.json();
      if (data.status === 'success') {
        if (data.processed_output) {
          setOutput(data.processed_output);
        } else if (data.output) {
          setOutput(data.output);
        } else {
          setError('No processed output received.');
          setLoading(false);
          return;
        }
        if (data.urls) {
          setUrlsData(data.urls);
        }
        if (data.raw_output) {
          setRawOutput(data.raw_output);
        }
      } else if (data.message) {
        setError(data.message);
      } else {
        setError('No output received.');
      }
    } catch (err: any) {
      setError(err.message || 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Knowledge Ingestion Engine</h1>
        <form className="ingest-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Blog/Guide URLs (one per line)</label>
            <textarea value={urls} onChange={handleUrlsChange} placeholder="https://example.com/blog-post-1&#10;https://example.com/blog-post-2&#10;https://example.com/blog-post-3" rows={4} style={{ resize: 'vertical' }} />
          </div>
          <div className="form-group">
            <label>Upload PDFs (multiple allowed)</label>
            <input type="file" accept="application/pdf" onChange={handlePdfsChange} multiple />
            {pdfs && pdfs.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ color: 'black', fontSize: '14px' }}>Selected files ({pdfs.length}):</span>
                  <button 
                    type="button" 
                    onClick={handleClearAllPdfs}
                    style={{ 
                      background: '#dc3545', 
                      color: 'white', 
                      border: 'none', 
                      padding: '4px 8px', 
                      borderRadius: '4px', 
                      cursor: 'pointer',
                      fontSize: '12px'
                    }}
                  >
                    Clear All
                  </button>
                </div>
                <ul style={{ paddingLeft: 18 }}>
                  {Array.from(pdfs).map((file, idx) => (
                    <li key={file.name + idx} style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'black' }}>
                      <span>{file.name}</span>
                      <button type="button" onClick={() => handleRemovePdf(idx)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.1em' }}>×</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="form-group">
            <label>Team ID <span style={{color: '#f88'}}>*</span></label>
            <input type="text" value={teamId} onChange={handleTeamIdChange} required />
          </div>
          <div className="form-group">
            <label>User ID</label>
            <input type="text" value={userId} onChange={handleUserIdChange} />
          </div>
          <div className="form-group">
            <label>Crawl Depth (for single URL only)</label>
            <select value={depth} onChange={handleDepthChange} disabled={Boolean(pdfs && pdfs.length > 0) || (urls.trim().split('\n').filter(Boolean).length > 1)}>
              <option value={0}>0 (Just this page)</option>
              <option value={1}>1 (Follow links once)</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </div>
          <div className="form-group">
            <label>Author Mode</label>
            <select value={authorMode} onChange={handleAuthorModeChange}>
              <option value="cost_saving">Cost Saving (200 chars, $0.001)</option>
              <option value="balanced">Balanced (500 chars, $0.002)</option>
              <option value="accuracy">Accuracy (1000 chars, $0.004)</option>
            </select>
            <small style={{ color: '#666', fontSize: '12px' }}>
              Controls how much PDF content is sent to OpenAI for author extraction. 
              Higher accuracy uses more content but costs more.
            </small>
          </div>
          <button 
            type="submit" 
            disabled={loading} 
            style={{
              background: loading ? '#ccc' : '#007bff',
              color: 'white',
              border: 'none',
              padding: '10px 20px',
              borderRadius: '4px',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1
            }}
          >
            {loading ? (
              <span style={{ display: 'flex', alignItems: 'center' }}>
                <div style={{
                  width: '16px',
                  height: '16px',
                  border: '2px solid #fff',
                  borderTop: '2px solid transparent',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  marginRight: '8px'
                }}></div>
                Processing...
              </span>
            ) : (
              'Process Content'
            )}
          </button>
        </form>
        {error && <div className="error">{error}</div>}
        
        {output && (
          <div className="output-preview">
            <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', alignItems: 'center' }}>
              <h2 style={{ margin: 0 }}>Output JSON</h2>
              <button 
                onClick={() => setShowRawOutput(!showRawOutput)}
                style={{ 
                  padding: '5px 10px', 
                  fontSize: '12px',
                  backgroundColor: showRawOutput ? '#007bff' : '#6c757d',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer'
                }}
              >
                {showRawOutput ? 'Show Processed' : 'Show Raw'}
              </button>
            </div>
            <div className="download-buttons">
              <button onClick={handleDownload}>Download Processed JSON</button>
              {rawOutput && <button onClick={handleDownloadRaw}>Download Raw JSON</button>}
              <button onClick={handleDownloadMarkdown}>Download Markdown</button>
            </div>
            
            {showRawOutput && rawOutput ? (
              <div>
                <h3>Raw Output (Unprocessed Data)</h3>
                <pre style={{ fontSize: '10px', maxHeight: '400px', overflow: 'auto' }}>
                  {JSON.stringify(rawOutput, null, 2)}
                </pre>
                {rawOutput.raw_data?.[0]?.code_blocks && (
                  <div style={{ marginTop: '20px' }}>
                    <h4>Code Blocks Found ({rawOutput.raw_data[0].code_blocks.length})</h4>
                    {rawOutput.raw_data[0].code_blocks.slice(0, 5).map((block: any, index: number) => (
                      <div key={index} style={{ marginBottom: '10px', padding: '10px', backgroundColor: '#f8f9fa', borderRadius: '4px' }}>
                        <strong>Block {block.index}:</strong>
                        <pre style={{ fontSize: '11px', whiteSpace: 'pre-wrap', marginTop: '5px' }}>
                          {block.content.substring(0, 200)}{block.content.length > 200 ? '...' : ''}
                        </pre>
                      </div>
                    ))}
                    {rawOutput.raw_data[0].code_blocks.length > 5 && (
                      <p>... and {rawOutput.raw_data[0].code_blocks.length - 5} more code blocks</p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div>
                <pre>{JSON.stringify(output, null, 2)}</pre>
                <h3>Formatted Content Preview:</h3>
                <div className="content-preview">
                  {output.items?.map((item, index) => (
                    <div key={index} className="content-item">
                      <h4>{item.title}</h4>
                      <div style={{ marginBottom: 8 }}>
                        <strong>Source: </strong>
                        {item.source_url && item.source_url.startsWith('http') ? (
                          <a href={item.source_url} target="_blank" rel="noopener noreferrer">{item.source_url}</a>
                        ) : (
                          <span>{item.source_url}</span>
                        )}
                      </div>
                      <div style={{ marginBottom: 8 }}>
                        <strong>Author: </strong>
                        <span>{item.author || 'Unknown'}</span>
                        {item.author_method && (
                          <span style={{ 
                            marginLeft: 8, 
                            padding: '2px 6px', 
                            borderRadius: '3px', 
                            fontSize: '11px',
                            backgroundColor: item.author_method.startsWith('openai') ? '#28a745' : '#ffc107',
                            color: item.author_method.startsWith('openai') ? 'white' : 'black'
                          }}>
                            {item.author_method.startsWith('openai') ? 
                              `🤖 OpenAI (${item.author_method.replace('openai_', '')})` : 
                              '📖 Manual'
                            }
                          </span>
                        )}
                      </div>
                      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}>
                        {item.content}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {urlsData.length > 0 && (
          <div className="urls-preview">
            <h2>Found URLs</h2>
            <div className="urls-list">
              {urlsData.map((urlData, index) => (
                <div key={index} className="url-entry">
                  <h3>Depth {urlData.depth_level}: {urlData.original_url}</h3>
                  <p>Found {urlData.found_urls.length} URLs:</p>
                  <ul>
                    {urlData.found_urls.map((foundUrl, urlIndex) => (
                      <li key={urlIndex} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={selectedUrls[foundUrl] ?? true}
                          onChange={() => handleUrlCheckbox(foundUrl)}
                          id={`url-checkbox-${index}-${urlIndex}`}
                        />
                        <label htmlFor={`url-checkbox-${index}-${urlIndex}`} style={{ color: 'black', cursor: 'pointer' }}>
                          <a href={foundUrl} target="_blank" rel="noopener noreferrer">
                            {foundUrl}
                          </a>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <button
              onClick={handleContinueToNextDepth}
              disabled={loading}
              style={{ marginTop: 16, padding: '8px 16px', fontSize: '1em', background: '#007bff', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer' }}
            >
              {loading ? 'Processing...' : 'Continue to next depth'}
            </button>
          </div>
        )}
      </header>
    </div>
  );
}

export default App;
