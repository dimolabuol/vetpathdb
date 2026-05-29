// Case details handling functionality
async function showCaseDetails(index) {
    const result = currentResults[index];
    window.currentCaseId = result.case_id; // Store case ID globally
    
    try {
        const response = await fetch(`/api/case/${result.case_id}`);
        const data = await response.json();
        
        // Create a sanitized copy of the case data without file contents
        const caseData = JSON.parse(JSON.stringify(data.case.data || {}));
        if (caseData.report_metadata) {
            delete caseData.report_metadata.file_contents;
        }
        
        const detailsHtml = generateCaseDetailsHtml(result.case_id, caseData);
        document.getElementById('caseDetails').innerHTML = detailsHtml;
        document.getElementById('caseModal').style.display = 'block';
        setupCollapsibleSections();
    } catch (error) {
        console.error('Error fetching case details:', error);
    }
}

function generateCaseDetailsHtml(caseId, caseData) {
    return `
        <div class="case-header">
            <div class="case-type-banner ${caseData.report_metadata?.report_type?.toLowerCase() || 'unknown'}" style="border-radius: 0">
                <i class="fas fa-file-medical"></i>
                ${caseData.report_metadata?.report_type || 'Unknown Type'} Report
                <button class="view-json-btn" onclick="viewFullJson('${caseId}')">
                    <i class="fas fa-code"></i> View JSON
                </button>
            </div>
            <div class="case-id-banner">
                <div class="case-header-main">
                    <h2>Case ${caseId}</h2>
                    ${caseData.case_keywords && caseData.case_keywords.length > 0 ? `
                        <div class="case-tags" style="margin-left: 0">
                            ${caseData.case_keywords.map(tag => `<span class="header-tag summary-item primary" style="margin-right: 8px; font-size: 0.85em; padding: 2px 8px"><i class="fas fa-tag"></i> ${tag}</span>`).join('')}
                        </div>
                    ` : ''}
                </div>
                <span class="case-date">${formatDate(caseData.report_metadata?.date_received)}</span>
            </div>
        </div>
        
        ${generateCaseSummary(caseData)}
        
        <div class="case-content">
            <div class="primary-info">
                ${generateFileSection(caseData)}
                ${generateSummarySection(caseData)}
                ${generateCommentSection(caseData)}
            </div>
            
            <div class="details-grid">
                <div class="details-column">
                    ${createDetailSection('Animal Details', caseData.animal_details, 'fa-paw')}
                    ${createDetailSection('Clinical Details', caseData.clinical_details, 'fa-stethoscope')}
                </div>
                <div class="details-column">
                    ${createDetailSection('Report Metadata', caseData.report_metadata, 'fa-clipboard')}
                </div>
            </div>
            
            <div class="full-width-sections">
                ${createDetailSection('Gross Findings', caseData.gross_findings, 'fa-search')}
                ${createDetailSection('Histopathology', caseData.histopathology, 'fa-microscope')}
                ${createDetailSection('Bacteriology', caseData.bacteriology, 'fa-bacteria')}
            </div>
        </div>
    `;
}

function generateCaseSummary(caseData) {
    const animal = caseData.animal_details || {};
    const histo = caseData.histopathology || {};
    const keywords = caseData.case_keywords || [];
    
    return `
        <div class="case-summary">
            <div class="summary-group">
                <i class="fas fa-paw"></i>
                <span class="summary-item primary">${animal.species || 'Unknown Species'}</span>
                <span class="summary-item">${animal.breed || 'Unknown Breed'}</span>
            </div>
            <div class="summary-group">
                <i class="fas fa-info-circle"></i>
                <span class="summary-item">${animal.age ? `${animal.age} years` : 'Age Unknown'}</span>
                <span class="summary-item">${animal.sex || 'Sex Unknown'}</span>
                <span class="summary-item">${animal.bodyweight ? `${animal.bodyweight} kg` : 'Weight Unknown'}</span>
            </div>
        </div>
    `;
}

function generateFileSection(caseData) {
    const filenames = caseData.report_metadata?.filenames || [];
    const extraFilenames = caseData.report_metadata?.extra_filenames || [];

    // Generate HTML for standard files
    const standardFilesHtml = filenames.map(filename => `
        <div class="file-item-group">
            <div class="file-name" title="${filename}">${filename}</div>
            <div class="file-item txt" onclick="showFileContent('${filename}')">
                <i class="fas fa-file-alt"></i>
                <span class="file-name">TXT</span>
            </div>
            <div class="file-item pdf" onclick="showPdfFile('${filename.replace(/\.(txt|md)$/, '.pdf')}')">
                <i class="fas fa-file-pdf"></i>
                <span class="file-name">PDF</span>
            </div>
        </div>
    `).join('');

    // Generate HTML for extra files
    const extraFilesHtml = extraFilenames.map(filename => `
        <div class="file-item-group">
            <div class="file-name" title="${filename}">${filename}</div>
            <div class="file-item txt" onclick="showExtraFileContent('${filename}')">
                <i class="fas fa-file-alt"></i>
                <span class="file-name">TXT</span>
            </div>
            <div class="file-item pdf" onclick="showExtraPdfFile('${filename.replace(/\.(txt|md)$/, '.pdf')}')">
                <i class="fas fa-file-pdf"></i>
                <span class="file-name">PDF</span>
            </div>
        </div>
    `).join('');

    // Only include the extra files section if there are extra files
    const extraFilesSection = extraFilenames.length > 0 ? `
        <h4>Submission Forms</h4>
        <div class="file-grid">
            ${extraFilesHtml}
        </div>
    ` : '';

    return `
        <div class="detail-section">
            <h3>Case Files</h3>
            <div class="detail-content">
                <div class="file-grid">
                    ${standardFilesHtml}
                </div>
                ${extraFilesSection}
            </div>
        </div>
    `;
}

function showPdfFile(filename) {
    // Remove -ocr suffix for PDF files
    const pdfFilename = filename.replace(/-ocr\.pdf$/, '.pdf');
    
    const pdfModal = document.createElement('div');
    pdfModal.className = 'file-modal';
    pdfModal.innerHTML = `
        <div class="file-modal-content pdf-modal">
            <div class="file-modal-header">
                <h3>${pdfFilename}</h3>
                <span class="close-button" onclick="this.closest('.file-modal').remove()">&times;</span>
            </div>
            <iframe src="/pdf/${currentCaseId}/${pdfFilename}" width="100%" height="100%"></iframe>
        </div>
    `;
    document.body.appendChild(pdfModal);
    
    // Add click handler to close when clicking outside
    pdfModal.addEventListener('click', function(event) {
        if (event.target === pdfModal) {
            pdfModal.remove();
        }
    });
}

function showExtraFileContent(filename) {
    // Add 'extra-' prefix to the filename as it's stored in the filestore
    const storedFilename = 'extra-' + filename;
    fetch(`/api/file-content/${encodeURIComponent(storedFilename)}`)
        .then(response => response.json())
        .then(data => {
            if (data && data.content) {
                showFileModal(filename, data.content); // Use the original filename for display
            } else {
                alert('File content not available.');
            }
        })
        .catch(error => {
            console.error('Error fetching extra file content:', error);
            alert('Error fetching extra file content.');
        });
}

function showExtraPdfFile(filename) {
    // Fetch PDF from the 'extra/' subdirectory
    const pdfFilename = filename.replace(/-ocr\.pdf$/, '.pdf');
    const pdfUrl = `/pdf/${currentCaseId}/extra/${pdfFilename}`;

    const pdfModal = document.createElement('div');
    pdfModal.className = 'file-modal';
    pdfModal.innerHTML = `
        <div class="file-modal-content pdf-modal">
            <div class="file-modal-header">
                <h3>${pdfFilename}</h3>
                <span class="close-button" onclick="this.closest('.file-modal').remove()">&times;</span>
            </div>
            <iframe src="${pdfUrl}" width="100%" height="100%"></iframe>
        </div>
    `;
    document.body.appendChild(pdfModal);

    // Add click handler to close when clicking outside
    pdfModal.addEventListener('click', function(event) {
        if (event.target === pdfModal) {
            pdfModal.remove();
        }
    });
}

function generateSummarySection(caseData) {
    return `
        <div class="detail-section">
            <h3>Summary</h3>
            <div class="detail-content">
                <p class="detail-value"><strong>${caseData.summary || 'No summary available'}</strong></p>
            </div>
        </div>
    `;
}

function generateCommentSection(caseData) {
    return `
        <div class="detail-section">
            <h3>Comment</h3>
            <div class="detail-content">
                <p class="detail-value">${caseData.comment || 'No comment available'}</p>
            </div>
        </div>
    `;
}

function createDetailSection(title, data, icon = 'fa-info-circle') {
    if (!data || Object.keys(data).length === 0) return '';
    
    return `
        <div class="detail-section">
            <h3><i class="fas ${icon}"></i> ${title}</h3>
            <div class="detail-content">
                ${createNestedTable(data)}
            </div>
        </div>
    `;
}

function createNestedTable(data, level = 0, isTissueSample = false) {
    const rows = Object.entries(data).map(([key, value]) => `
        <tr>
            <td class="detail-label" ${isTissueSample ? `data-field="${key}"` : ''}>${formatFieldName(key)}</td>
            <td class="detail-value" ${isTissueSample ? `data-field="${key}"` : ''}>${formatValue(value, level)}</td>
        </tr>
    `).join('');

    const tableClass = level > 0 ? 'nested-table' : 'detail-table';
    const dataLevel = level > 0 ? `data-level="${level}"` : '';
    const dataSection = isTissueSample ? 'data-section="tissue-samples"' : '';

    return `
        <table class="${tableClass}" ${dataLevel} ${dataSection}>
            ${rows}
        </table>
    `;
}

function formatFieldName(name) {
    return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatValue(value, level = 0) {
    if (value === null || value === undefined) {
        return '<span class="empty-value">No data</span>';
    }

    if (Array.isArray(value)) {
        return formatArray(value);
    }

    if (typeof value === 'object') {
        if (Object.keys(value).length === 0) {
            return '<span class="empty-value">No items</span>';
        }
        return createNestedTable(value, level + 1);
    }

    if (typeof value === 'boolean') {
        return `<span class="boolean-value">
            <i class="fas fa-${value ? 'check' : 'times'}"></i> ${value ? 'Yes' : 'No'}
        </span>`;
    }

    if (typeof value === 'number') {
        return formatNumber(value);
    }

    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
        return formatDate(value);
    }

    return `<span class="text-value">${value.toString()}</span>`;
}

function formatDate(dateStr) {
    if (!dateStr) return '<span class="empty-value">No date</span>';
    try {
        const date = new Date(dateStr);
        return `<span class="date-value" title="${date.toLocaleString()}">${date.toLocaleDateString()}</span>`;
    } catch {
        return `<span class="invalid-value">${dateStr}</span>`;
    }
}

function formatNumber(num) {
    if (num === null || num === undefined) return '<span class="empty-value">No value</span>';
    if (isNaN(num)) return '<span class="invalid-value">Invalid number</span>';
    return `<span class="number-value">${Number(num).toLocaleString()}</span>`;
}

function formatArray(arr) {
    if (!arr || arr.length === 0) return '<span class="empty-value">No items</span>';
    return `<div class="array-container">
        ${arr.map(item => `<span class="array-item">${formatValue(item)}</span>`).join('')}
    </div>`;
}

function setupCollapsibleSections() {
    document.querySelectorAll('.detail-section h3').forEach(header => {
        header.addEventListener('click', () => {
            const section = header.parentElement;
            section.classList.toggle('collapsed');
        });
    });
}

function expandAllSections() {
    document.querySelectorAll('.detail-section').forEach(section => {
        section.classList.remove('collapsed');
    });
}

function collapseAllSections() {
    document.querySelectorAll('.detail-section').forEach(section => {
        section.classList.add('collapsed');
    });
}

function clearResults() {
    document.getElementById('searchResults').innerHTML = '';
    document.getElementById('analysisResults').innerHTML = '';
}

function setupModalHandlers() {
    // Close modal when clicking outside of it
    window.onclick = function(event) {
        const modal = document.getElementById('caseModal');
        if (event.target === modal) {
            closeModal();
        }
    }

    // Close modal with Escape key
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') {
            closeModal();
        }
    });
}

function closeModal() {
    document.getElementById('caseModal').style.display = 'none';
    window.currentCaseId = null; // Clear case ID when modal is closed
}

// Function to view the full JSON of a case
function viewFullJson(caseId) {
    fetch(`/api/case/${caseId}`)
        .then(response => response.json())
        .then(data => {
            // Create a modal to display the JSON
            const jsonModal = document.createElement('div');
            jsonModal.className = 'file-modal';
            jsonModal.innerHTML = `
                <div class="file-modal-content json-modal">
                    <div class="file-modal-header">
                        <h3>Full JSON for Case ${caseId}</h3>
                        <div class="json-actions">
                            <button onclick="copyJsonToClipboard()" class="json-action-btn">
                                <i class="fas fa-copy"></i> Copy
                            </button>
                            <button onclick="downloadJson('case_${caseId}.json')" class="json-action-btn">
                                <i class="fas fa-download"></i> Download
                            </button>
                            <span class="close-button" onclick="this.closest('.file-modal').remove()">&times;</span>
                        </div>
                    </div>
                    <pre id="jsonContent" class="json-content">${JSON.stringify(data.case, null, 2)}</pre>
                </div>
            `;
            document.body.appendChild(jsonModal);
            
            // Add click handler to close when clicking outside
            jsonModal.addEventListener('click', function(event) {
                if (event.target === jsonModal) {
                    jsonModal.remove();
                }
            });
            
            // Store the JSON data for copy/download operations
            window.currentJsonData = data.case;
        })
        .catch(error => {
            console.error('Error fetching case JSON:', error);
            alert('Error fetching case JSON data.');
        });
}

// Function to copy JSON to clipboard
function copyJsonToClipboard() {
    const jsonStr = JSON.stringify(window.currentJsonData, null, 2);
    navigator.clipboard.writeText(jsonStr)
        .then(() => {
            // Show a temporary success message
            const copyBtn = document.querySelector('.json-actions .json-action-btn');
            const originalText = copyBtn.innerHTML;
            copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            setTimeout(() => {
                copyBtn.innerHTML = originalText;
            }, 2000);
        })
        .catch(err => {
            console.error('Failed to copy JSON: ', err);
            alert('Failed to copy to clipboard');
        });
}

// Function to download JSON as a file
function downloadJson(filename) {
    const jsonStr = JSON.stringify(window.currentJsonData, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}
