// File handling functionality

// Escape HTML entities for security
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Configure marked for rendering
if (typeof marked !== 'undefined') {
    marked.setOptions({
        gfm: true,        // GitHub Flavored Markdown (tables, strikethrough, etc.)
        breaks: true,     // Convert \n to <br>
        headerIds: false, // Don't add IDs to headers
        mangle: false     // Don't escape email addresses
    });
}

// Render content - use marked for .md files, escaped text for others
function renderFileContent(filename, content) {
    const isMarkdown = filename.toLowerCase().endsWith('.md');

    if (isMarkdown && typeof marked !== 'undefined') {
        // Use marked.js for full markdown support (tables, etc.)
        return marked.parse(content);
    } else if (isMarkdown) {
        // Fallback to basic parser if marked not loaded
        const escaped = escapeHtml(content);
        return parseMarkdown(escaped);
    } else {
        // Plain text - just escape and preserve whitespace
        return escapeHtml(content);
    }
}

async function showFileContent(filename) {
    try {
        // Get current case ID from global state
        const caseId = window.currentCaseId;
        if (!caseId) {
            throw new Error('No case ID available');
        }
        
        const response = await fetch(`/api/file-content/${encodeURIComponent(filename)}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        
        showFileModal(filename, data.content);
    } catch (error) {
        console.error('Error fetching file content:', error);
        alert('Error loading file content');
    }
}

function showFileModal(filename, content) {
    const fileModal = document.createElement('div');
    fileModal.className = 'file-modal';
    const isMarkdown = filename.toLowerCase().endsWith('.md');
    const renderedContent = renderFileContent(filename, content);
    const contentClass = isMarkdown ? 'file-content markdown-content' : 'file-content';
    const contentTag = isMarkdown ? 'div' : 'pre';

    fileModal.innerHTML = `
        <div class="file-modal-content">
            <div class="file-modal-header">
                <h3>${escapeHtml(filename)}</h3>
                <span class="close-button" onclick="this.closest('.file-modal').remove()">&times;</span>
            </div>
            <${contentTag} class="${contentClass}">${renderedContent}</${contentTag}>
        </div>
    `;

    document.body.appendChild(fileModal);
    
    fileModal.addEventListener('click', (e) => {
        if (e.target === fileModal) {
            fileModal.remove();
        }
    });
}

async function downloadCaseJson(index) {
    const result = currentResults[index];
    
    try {
        const response = await fetch(`/api/case/${result.case_id}`);
        const data = await response.json();
        const fullCase = data.case;
        const json = JSON.stringify(fullCase, null, 2);
        
        downloadFile(
            `case_${result.case_id}.json`,
            json,
            'application/json'
        );
    } catch (err) {
        console.error('Failed to download case JSON:', err);
        alert('Failed to download case JSON. Error: ' + err.message);
    }
}

function downloadFile(filename, content, type) {
    const blob = new Blob([content], { type: type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}
