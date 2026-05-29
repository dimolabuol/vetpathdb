// Analysis-related functionality
async function showSpeciesDistribution() {
    try {
        clearResults();
        // Hide the search placeholder immediately
        document.getElementById('searchPlaceholder').style.display = 'none';
        
        const query = {
            type: 'aggregate',
            pipeline: [
                {
                    $group: {
                        _id: '$data.animal_details.species',
                        count: { $sum: 1 }
                    }
                },
                { $sort: { count: -1 } }
            ]
        };

        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(query)
        });
        
        const data = await response.json();
        
        let html = '<div class="detail-section">';
        html += '<h3>Species Distribution</h3>';
        html += '<div class="detail-content">';
        html += '<table class="detail-table"><tr><th>Species</th><th>Count</th></tr>';
        data.results.forEach(s => {
            html += `<tr><td class="detail-label">${s._id || 'Unknown'}</td><td class="detail-value">${s.count}</td></tr>`;
        });
        html += '</table></div></div>';
        
        document.getElementById('analysisResults').innerHTML = html;
    } catch (error) {
        console.error('Error:', error);
    }
}

async function showMorphologicalAnalysis() {
    try {
        clearResults();
        // Hide the search placeholder immediately
        document.getElementById('searchPlaceholder').style.display = 'none';
        
        const response = await fetch('/api/morphological-analysis');
        const data = await response.json();
        
        let html = '<div class="analysis-result">';
        html += '<h3>Morphological Features Analysis</h3>';
        
        // Create summary charts container
        html += `
            <div class="summary-charts">
                <div class="chart-container">
                    <canvas id="sizeSummaryChart"></canvas>
                </div>
                <div class="chart-container">
                    <canvas id="shapeSummaryChart"></canvas>
                </div>
            </div>`;
        
        data.analysis.forEach(tumor => {
            if (!tumor.tumor_type) return;
            
            html += `
                <div class="detail-section">
                    <h3>${tumor.tumor_type} <span class="badge">${tumor.total_cases} cases</span></h3>
                    <div class="detail-content">
                        <div class="feature-grid">`;
            
            // Size features card
            if (Object.keys(tumor.features.size).length > 0) {
                html += `
                    <div class="feature-card">
                        <div class="feature-header">Cell Size Distribution</div>
                        <div class="feature-values">`;
                
                Object.entries(tumor.features.size)
                    .sort((a, b) => b[1].count - a[1].count)
                    .forEach(([size, data]) => {
                        html += `
                            <div class="feature-value">
                                <span class="value-label">${size.charAt(0).toUpperCase() + size.slice(1)}</span>
                                <div class="value-bar-container">
                                    <div class="value-bar" style="width: ${data.percentage}%"></div>
                                    <span class="value-count">${data.count} (${data.percentage}%)</span>
                                </div>
                            </div>`;
                    });
                
                html += `</div></div>`;
            }
            
            // Shape features card
            if (Object.keys(tumor.features.shape).length > 0) {
                html += `
                    <div class="feature-card">
                        <div class="feature-header">Cell Shape Characteristics</div>
                        <div class="feature-values">`;
                
                Object.entries(tumor.features.shape)
                    .sort((a, b) => b[1].count - a[1].count)
                    .forEach(([shape, data]) => {
                        html += `
                            <div class="feature-value">
                                <span class="value-label">${shape.charAt(0).toUpperCase() + shape.slice(1)}</span>
                                <div class="value-bar-container">
                                    <div class="value-bar" style="width: ${data.percentage}%"></div>
                                    <span class="value-count">${data.count} (${data.percentage}%)</span>
                                </div>
                            </div>`;
                    });
                
                html += `</div></div>`;
            }
            
            html += `</div></div></div>`;
        });
        
        html += '</div>';
        document.getElementById('analysisResults').innerHTML = html;
        
        // Create summary charts
        createSummaryCharts(data.analysis);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function showIHCPatterns() {
    try {
        clearResults();
        // Hide the search placeholder immediately
        document.getElementById('searchPlaceholder').style.display = 'none';
        
        const response = await fetch('/api/ihc-patterns');
        const data = await response.json();
        
        let html = '<div class="analysis-result">';
        html += '<h3>Immunohistochemistry Marker Patterns</h3>';
        
        // Create single chart container
        html += `
            <div class="chart-container" style="height: 300px; margin: 20px 0;">
                <canvas id="markerDistributionChart"></canvas>
            </div>`;

        // Process each tumor type
        Object.entries(data.patterns).forEach(([tumorType, markers]) => {
            if (!markers.length) return;
            
            html += `
                <div class="detail-section">
                    <h3>${tumorType} <span class="badge">${markers.length} markers</span></h3>
                    <div class="detail-content">
                        <div class="feature-grid">`;

            markers.sort((a, b) => b.total_cases - a.total_cases);
            
            markers.forEach(marker => {
                html += `
                    <div class="feature-card">
                        <div class="feature-header">${marker.marker} (${marker.total_cases} cases)</div>
                        <div class="feature-values">`;

                // Intensity patterns
                if (Object.keys(marker.patterns.intensity).length > 0) {
                    html += `<div class="pattern-section">
                        <h5>Intensity Patterns</h5>`;
                    
                    Object.entries(marker.patterns.intensity)
                        .sort((a, b) => b[1].count - a[1].count)
                        .forEach(([intensity, data]) => {
                            html += `
                                <div class="feature-value">
                                    <span class="value-label">${intensity.charAt(0).toUpperCase() + intensity.slice(1)}</span>
                                    <div class="value-bar-container">
                                        <div class="value-bar ${intensity}" style="width: ${data.percentage}%"></div>
                                        <span class="value-count">${data.count} (${data.percentage}%)</span>
                                    </div>
                                </div>`;
                        });
                    html += '</div>';
                }

                // Distribution patterns
                if (Object.keys(marker.patterns.distribution).length > 0) {
                    html += `<div class="pattern-section">
                        <h5>Distribution Patterns</h5>`;
                    
                    Object.entries(marker.patterns.distribution)
                        .sort((a, b) => b[1].count - a[1].count)
                        .forEach(([distribution, data]) => {
                            html += `
                                <div class="feature-value">
                                    <span class="value-label">${distribution.charAt(0).toUpperCase() + distribution.slice(1)}</span>
                                    <div class="value-bar-container">
                                        <div class="value-bar" style="width: ${data.percentage}%"></div>
                                        <span class="value-count">${data.count} (${data.percentage}%)</span>
                                    </div>
                                </div>`;
                        });
                    html += '</div>';
                }

                html += `</div></div>`;
            });
            
            html += `</div></div></div>`;
        });
        
        html += '</div>';
        document.getElementById('analysisResults').innerHTML = html;
        
        // Create summary charts
        createIHCSummaryCharts(data.patterns);
    } catch (error) {
        console.error('Error:', error);
    }
}

async function showBreedPatterns() {
    try {
        clearResults();
        // Hide the search placeholder immediately
        document.getElementById('searchPlaceholder').style.display = 'none';
        
        const response = await fetch('/api/breed-patterns');
        const data = await response.json();
        
        // Group patterns by species
        const speciesGroups = data.patterns.reduce((acc, p) => {
            const species = p._id.species || 'Unknown Species';
            if (!acc[species]) acc[species] = [];
            acc[species].push(p);
            return acc;
        }, {});

        let html = '<div class="analysis-result">';
        html += '<h3>Breed-Specific Disease Patterns</h3>';
        
        // Add species navigation
        html += '<div class="species-nav">';
        Object.keys(speciesGroups).sort().forEach(species => {
            html += `<button class="species-nav-btn" onclick="scrollToSpecies('${species.replace(/'/g, "\\'")}')">${species}</button>`;
        });
        html += '</div>';
        
        // Create sections for each species
        Object.entries(speciesGroups).sort(([a], [b]) => a.localeCompare(b)).forEach(([species, breeds]) => {
            html += `
                <div class="species-section" id="species-${species.toLowerCase().replace(/\s+/g, '-')}">
                    <h4 class="species-header">${species} <span class="species-count">${breeds.length} breeds</span></h4>
                    <div class="breed-table-container">
                        <table class="breed-table">
                            <thead>
                                <tr>
                                    <th>Breed</th>
                                    <th>Cases</th>
                                    <th>Age (yrs)</th>
                                    <th>Sex Distribution</th>
                                    <th>Top Diagnoses</th>
                                    <th>Common Tumors</th>
                                    <th>Common Locations</th>
                                </tr>
                            </thead>
                            <tbody>`;
            
            breeds.sort((a, b) => b.count - a.count).forEach(p => {
                const breed = p._id.breed || 'Unknown Breed';
                
                // Calculate statistics
                const ages = p.age_stats.filter(a => a != null);
                const avgAge = ages.length ? (ages.reduce((a, b) => a + b, 0) / ages.length).toFixed(1) : 'N/A';
                const medianAge = ages.length ? calculateMedian(ages).toFixed(1) : 'N/A';
                
                // Process sex statistics
                const sexStats = processSexStats(p.sex_stats);
                
                // Get top items
                const diagnoses = getTopItems(p.diagnoses, 3);
                const tumorTypes = getTopItems(p.tumor_types.filter(t => t), 2);
                const locations = getTopItems(p.locations.filter(l => l), 2);
                
                html += `
                    <tr>
                        <td class="breed-name">
                            <strong>${breed}</strong>
                            <span class="tumor-rate">${p.tumor_percentage.toFixed(1)}% tumors</span>
                        </td>
                        <td class="case-count">${p.count}</td>
                        <td class="age-stats">avg ${avgAge}<br>med ${medianAge}</td>
                        <td class="sex-stats">
                            ${Object.entries(sexStats)
                                .sort((a, b) => b[1] - a[1])
                                .map(([sex, count]) => 
                                    `<span class="sex-stat">${sex}: ${count}</span>`)
                                .join('<br>')}
                        </td>
                        <td class="disease-patterns">
                            <div class="pattern-section">
                                <h6>Top Diagnoses</h6>
                                ${diagnoses.map(([diagnosis, count]) => 
                                    `<span class="diagnosis-pill" title="${diagnosis}">${truncateText(diagnosis, 25)} (${count})</span>`
                                ).join('')}
                            </div>
                            <div class="pattern-section">
                                <h6>Clinical Presentations</h6>
                                ${getTopItems((p.clinical_diagnoses || []).concat(p.clinical_suspicions || []).filter(x => x), 3)
                                    .map(([diagnosis, count]) => 
                                        `<span class="clinical-pill" title="${diagnosis}">${truncateText(diagnosis, 25)} (${count})</span>`
                                    ).join('')}
                            </div>
                            <div class="pattern-section">
                                <h6>Disease Categories</h6>
                                <div class="category-stats">
                                    <span class="stat-pill tumor" title="Neoplastic cases">
                                        ${Math.round((p.tumor_cases/p.count)*100)}% Neoplastic
                                    </span>
                                    <span class="stat-pill inflammatory" title="Inflammatory cases">
                                        ${Math.round((p.inflammatory_cases/p.count)*100)}% Inflammatory
                                    </span>
                                    <span class="stat-pill degenerative" title="Degenerative cases">
                                        ${Math.round((p.degenerative_cases/p.count)*100)}% Degenerative
                                    </span>
                                </div>
                            </div>
                        </td>
                    </tr>`;
            });
            
            html += '</tbody></table></div></div>';
        });
        
        html += '</div>';
        document.getElementById('analysisResults').innerHTML = html;
    } catch (error) {
        console.error('Error:', error);
    }
}

async function showDiagnosticTimeline() {
    try {
        clearResults();
        // Hide the search placeholder immediately
        document.getElementById('searchPlaceholder').style.display = 'none';
        
        const response = await fetch('/api/diagnostic-timeline');
        const data = await response.json();
        
        let html = '<div class="analysis-result">';
        html += '<h3>Diagnostic Keyword Trends Over Time</h3>';
        
        // Add canvas for the chart
        html += '<canvas id="timelineChart" style="width: 100%; height: 400px; margin: 20px 0;"></canvas>';
        
        // Create summary table
        html += '<div class="timeline-summary">';
        html += '<h4>Top Keywords by Year</h4>';
        html += '<div class="timeline-grid">';
        
        data.timeline.forEach(yearData => {
            html += `
                <div class="year-card">
                    <h5>${yearData.year}</h5>
                    <div class="keyword-list">
                        ${yearData.keywords.map(k => 
                            `<div class="keyword-item">
                                <span class="keyword-term">${k.term}</span>
                                <span class="keyword-count">${k.count}</span>
                             </div>`
                        ).join('')}
                    </div>
                </div>
            `;
        });
        
        html += '</div></div></div>';
        document.getElementById('analysisResults').innerHTML = html;
        
        // Create the timeline chart
        createTimelineChart(data.timeline);
    } catch (error) {
        console.error('Error:', error);
    }
}

// Helper functions for analysis
function calculateMedian(numbers) {
    const sorted = numbers.slice().sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) {
        return (sorted[middle - 1] + sorted[middle]) / 2;
    }
    return sorted[middle];
}

function processSexStats(sexStats) {
    return sexStats.reduce((acc, s) => {
        if (!s || !s.sex || typeof s.sex !== 'string' || s.sex === ':' || s.sex.toLowerCase().includes('not')) {
            return acc;
        }
        const key = `${s.sex}${s.neutered === 'yes' ? ' (n)' : ''}`;
        if (!acc[key]) acc[key] = 0;
        acc[key]++;
        return acc;
    }, {});
}

function getTopItems(items, limit) {
    const counts = items.reduce((acc, item) => {
        if (!item || item === '') return acc;
        if (!acc[item]) acc[item] = 0;
        acc[item]++;
        return acc;
    }, {});
    
    return Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, limit);
}

function truncateText(text, maxLength) {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

// Database Explorer functionality
let currentExplorerData = null;

async function showDatabaseExplorer() {
    try {
        clearResults();
        document.getElementById('searchPlaceholder').style.display = 'none';

        // Show loading state
        document.getElementById('analysisResults').innerHTML = '<div class="loading">Loading database schema...</div>';

        const response = await fetch('/api/database-explorer');
        const data = await response.json();

        currentExplorerData = data;

        let html = '<div class="explorer-container">';
        html += '<h3>Database Explorer</h3>';
        html += `<p class="explorer-summary">Total Documents: <strong>${data.total_documents.toLocaleString()}</strong></p>`;

        // Create two-column layout
        html += '<div class="explorer-layout">';

        // Left panel - Schema Tree
        html += '<div class="explorer-panel explorer-tree-panel">';
        html += '<h4>Schema Structure</h4>';
        html += '<div class="field-tree">';
        html += buildSchemaTree(data.schema);
        html += '</div></div>';

        // Right panel - Search, Field Details & Query Builder
        html += '<div class="explorer-panel explorer-detail-panel">';

        // Search UI
        html += '<div class="explorer-search-panel">';
        html += '<h4>Search Database</h4>';
        html += '<div class="search-input-group">';
        html += '<input type="text" id="explorerSearchInput" class="explorer-search-box" placeholder="Search database...">';
        html += '<button class="search-btn" onclick="executeExplorerSearch()"><i class="fas fa-search"></i> Search</button>';
        html += '</div>';
        html += '<div class="search-filter-group">';
        html += '<label>Search in:</label>';
        html += '<select id="searchFieldFilter" class="field-select">';
        html += '<option value="all">All Fields</option>';
        html += '<option value="diagnosis">Diagnosis & Tumor</option>';
        html += '<option value="clinical">Clinical Details</option>';
        html += '<option value="animal">Animal Details</option>';
        html += '<option value="tumor">Tumor Type & Location</option>';
        html += '</select>';
        html += '</div>';
        html += '<div id="searchResults" style="display:none;"></div>';
        html += '</div>';

        html += '<div id="fieldDetails">';
        html += '<p class="placeholder-text">Click on a field to see details and statistics</p>';
        html += '</div>';
        html += '<div id="queryBuilder" style="display:none;">';
        html += buildQueryBuilderUI();
        html += '</div>';
        html += '</div>';

        html += '</div></div>';

        document.getElementById('analysisResults').innerHTML = html;

        // Attach event listeners
        attachExplorerEventListeners();

    } catch (error) {
        console.error('Error:', error);
        document.getElementById('analysisResults').innerHTML =
            '<div class="error">Error loading database explorer. Please try again.</div>';
    }
}

function buildSchemaTree(schema, level = 0, parentPath = '') {
    let html = '<ul class="tree-level">';

    for (const [key, value] of Object.entries(schema)) {
        const currentPath = parentPath ? `${parentPath}.${key}` : key;
        const hasChildren = value.children && Object.keys(value.children).length > 0;
        const isExpandable = hasChildren || value.type === 'object';

        html += '<li class="tree-node">';

        if (isExpandable) {
            html += `<span class="tree-toggle" data-path="${currentPath}">▶</span>`;
        } else {
            html += '<span class="tree-spacer"></span>';
        }

        const icon = getFieldIcon(value.type);
        html += `<span class="field-item ${hasChildren ? '' : 'field-leaf'}" data-path="${value.path || currentPath}" data-type="${value.type}">`;
        html += `<i class="fas fa-${icon}"></i> ${key}`;
        html += `<span class="field-type">${value.type}</span>`;
        html += '</span>';

        if (hasChildren) {
            html += '<div class="tree-children" style="display:none;">';
            html += buildSchemaTree(value.children, level + 1, currentPath);
            html += '</div>';
        }

        html += '</li>';
    }

    html += '</ul>';
    return html;
}

function getFieldIcon(type) {
    const icons = {
        'string': 'font',
        'number': 'hashtag',
        'mixed': 'question-circle',
        'object': 'folder',
        'array': 'list'
    };
    return icons[type] || 'circle';
}

function attachExplorerEventListeners() {
    // Toggle tree nodes
    document.querySelectorAll('.tree-toggle').forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const node = e.target.closest('.tree-node');
            const children = node.querySelector('.tree-children');

            if (children) {
                const isVisible = children.style.display !== 'none';
                children.style.display = isVisible ? 'none' : 'block';
                e.target.textContent = isVisible ? '▶' : '▼';
            }
        });
    });

    // Field click handlers
    document.querySelectorAll('.field-leaf').forEach(field => {
        field.addEventListener('click', async (e) => {
            e.stopPropagation();

            // Remove previous selection
            document.querySelectorAll('.field-leaf').forEach(f => f.classList.remove('selected'));
            field.classList.add('selected');

            const fieldPath = field.dataset.path;
            const fieldType = field.dataset.type;

            await showFieldDetails(fieldPath, fieldType);
        });
    });

    // Search box Enter key handler
    const searchInput = document.getElementById('explorerSearchInput');
    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeExplorerSearch();
            }
        });
    }
}

async function showFieldDetails(fieldPath, fieldType) {
    const detailsDiv = document.getElementById('fieldDetails');
    detailsDiv.innerHTML = '<div class="loading">Loading field statistics...</div>';

    // Check if we have cached stats
    const cachedStats = currentExplorerData.field_stats[fieldPath];

    if (cachedStats) {
        displayFieldStats(fieldPath, fieldType, cachedStats);
    } else {
        // Fetch completeness stats
        try {
            const response = await fetch('/api/database-explorer/query', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query_type: 'field_completeness',
                    field_path: fieldPath
                })
            });

            const data = await response.json();
            displayFieldCompleteness(fieldPath, fieldType, data);

        } catch (error) {
            console.error('Error fetching field details:', error);
            detailsDiv.innerHTML = '<div class="error">Error loading field details</div>';
        }
    }

    // Show query builder
    document.getElementById('queryBuilder').style.display = 'block';
    updateQueryBuilder(fieldPath);
}

function displayFieldStats(fieldPath, fieldType, stats) {
    let html = '<div class="field-details">';
    html += `<h4>${fieldPath}</h4>`;
    html += `<p class="field-meta">Type: <strong>${fieldType}</strong> | Unique Values: <strong>${stats.unique_count}</strong></p>`;

    if (stats.top_values && stats.top_values.length > 0) {
        html += '<h5>Top Values</h5>';
        html += '<table class="stats-table">';
        html += '<thead><tr><th>Value</th><th>Count</th><th>%</th></tr></thead>';
        html += '<tbody>';

        const total = currentExplorerData.total_documents;
        stats.top_values.forEach(v => {
            const percentage = ((v.count / total) * 100).toFixed(1);
            const displayValue = v.value === null ? '<em>null</em>' : v.value;
            html += `<tr><td>${displayValue}</td><td>${v.count.toLocaleString()}</td><td>${percentage}%</td></tr>`;
        });

        html += '</tbody></table>';
    }

    html += '</div>';
    document.getElementById('fieldDetails').innerHTML = html;
}

function displayFieldCompleteness(fieldPath, fieldType, data) {
    let html = '<div class="field-details">';
    html += `<h4>${fieldPath}</h4>`;
    html += `<p class="field-meta">Type: <strong>${fieldType}</strong></p>`;

    html += '<div class="completeness-stats">';
    html += `<p>Total Documents: <strong>${data.total_documents.toLocaleString()}</strong></p>`;
    html += `<p>Non-Null Values: <strong>${data.non_null_count.toLocaleString()}</strong></p>`;
    html += `<p>Completeness: <strong>${data.completeness_percentage}%</strong></p>`;
    html += '<div class="completeness-bar">';
    html += `<div class="completeness-fill" style="width: ${data.completeness_percentage}%"></div>`;
    html += '</div>';
    html += '</div>';

    html += '</div>';
    document.getElementById('fieldDetails').innerHTML = html;
}

function buildQueryBuilderUI() {
    let html = '<div class="query-builder">';
    html += '<h5>Quick Queries</h5>';
    html += '<div class="query-buttons">';
    html += '<button class="query-btn" onclick="runFieldDistribution()"><i class="fas fa-chart-bar"></i> Value Distribution</button>';
    html += '<button class="query-btn" onclick="showCrossFieldAnalysis()"><i class="fas fa-project-diagram"></i> Cross-Field Analysis</button>';
    html += '</div>';
    html += '<div id="queryResults"></div>';
    html += '</div>';
    return html;
}

function updateQueryBuilder(fieldPath) {
    window.currentSelectedField = fieldPath;
}

async function runFieldDistribution() {
    if (!window.currentSelectedField) {
        alert('Please select a field first');
        return;
    }

    const resultsDiv = document.getElementById('queryResults');
    resultsDiv.innerHTML = '<div class="loading">Running query...</div>';

    try {
        const response = await fetch('/api/database-explorer/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query_type: 'field_distribution',
                field_path: window.currentSelectedField,
                limit: 50
            })
        });

        const data = await response.json();

        let html = '<div class="query-result">';
        html += `<h6>Distribution for ${data.field}</h6>`;
        html += '<table class="stats-table">';
        html += '<thead><tr><th>Value</th><th>Count</th></tr></thead>';
        html += '<tbody>';

        data.results.forEach(r => {
            const displayValue = r.value === null ? '<em>null</em>' : r.value;
            html += `<tr><td>${displayValue}</td><td>${r.count.toLocaleString()}</td></tr>`;
        });

        html += '</tbody></table>';
        html += '</div>';

        resultsDiv.innerHTML = html;

    } catch (error) {
        console.error('Error running query:', error);
        resultsDiv.innerHTML = '<div class="error">Error running query</div>';
    }
}

function showCrossFieldAnalysis() {
    // Create modal or inline form for selecting second field
    const resultsDiv = document.getElementById('queryResults');

    let html = '<div class="cross-field-form">';
    html += '<h6>Cross-Field Analysis</h6>';
    html += `<p>Field 1: <strong>${window.currentSelectedField}</strong></p>`;
    html += '<label>Select Field 2:</label>';
    html += '<select id="field2Select" class="field-select">';
    html += '<option value="">-- Select a field --</option>';

    // Add common fields
    const commonFields = [
        'data.animal_details.species',
        'data.animal_details.breed',
        'data.animal_details.sex',
        'data.histopathology.tumor_type',
        'data.histopathology.tumor_location',
        'data.report_metadata.report_type'
    ];

    commonFields.forEach(field => {
        if (field !== window.currentSelectedField) {
            html += `<option value="${field}">${field}</option>`;
        }
    });

    html += '</select>';
    html += '<button class="query-btn" onclick="executeCrossFieldAnalysis()">Run Analysis</button>';
    html += '<div id="crossFieldResults"></div>';
    html += '</div>';

    resultsDiv.innerHTML = html;
}

async function executeCrossFieldAnalysis() {
    const field2 = document.getElementById('field2Select').value;

    if (!field2) {
        alert('Please select a second field');
        return;
    }

    const resultsDiv = document.getElementById('crossFieldResults');
    resultsDiv.innerHTML = '<div class="loading">Running analysis...</div>';

    try {
        const response = await fetch('/api/database-explorer/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query_type: 'cross_field_analysis',
                field1: window.currentSelectedField,
                field2: field2,
                limit: 30
            })
        });

        const data = await response.json();

        let html = '<div class="query-result">';
        html += `<h6>Relationship: ${data.field1} × ${data.field2}</h6>`;
        html += '<table class="stats-table">';
        html += '<thead><tr><th>' + data.field1.split('.').pop() + '</th><th>' + data.field2.split('.').pop() + '</th><th>Count</th></tr></thead>';
        html += '<tbody>';

        data.results.forEach(r => {
            const val1 = r.field1_value === null ? '<em>null</em>' : r.field1_value;
            const val2 = r.field2_value === null ? '<em>null</em>' : r.field2_value;
            html += `<tr><td>${val1}</td><td>${val2}</td><td>${r.count.toLocaleString()}</td></tr>`;
        });

        html += '</tbody></table>';
        html += '</div>';

        resultsDiv.innerHTML = html;

    } catch (error) {
        console.error('Error running cross-field analysis:', error);
        resultsDiv.innerHTML = '<div class="error">Error running analysis</div>';
    }
}

// Database Explorer Search Functions
let currentSearchResults = null;
let currentSearchSkip = 0;

async function executeExplorerSearch() {
    const searchInput = document.getElementById('explorerSearchInput');
    const fieldFilter = document.getElementById('searchFieldFilter');
    const query = searchInput.value.trim();

    if (!query) {
        alert('Please enter a search term');
        return;
    }

    // Reset pagination
    currentSearchSkip = 0;

    // Hide field details and query builder
    document.getElementById('fieldDetails').style.display = 'none';
    document.getElementById('queryBuilder').style.display = 'none';

    // Show and populate search results
    const resultsDiv = document.getElementById('searchResults');
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '<div class="loading">Searching database...</div>';

    try {
        const response = await fetch('/api/database-explorer/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                field_filter: fieldFilter.value,
                skip: currentSearchSkip,
                limit: 50
            })
        });

        const data = await response.json();
        currentSearchResults = data;

        displaySearchResults(data);

    } catch (error) {
        console.error('Error searching database:', error);
        resultsDiv.innerHTML = '<div class="error">Error executing search. Please try again.</div>';
    }
}

function displaySearchResults(data) {
    const resultsDiv = document.getElementById('searchResults');

    let html = '<div class="search-results-container">';
    html += '<div class="search-results-header">';
    html += `<h5>Search Results for "${data.query}"</h5>`;
    html += `<p class="result-count">Showing ${data.returned_count} of ${data.total_count.toLocaleString()} results</p>`;
    html += '<button class="clear-search-btn" onclick="clearExplorerSearch()"><i class="fas fa-times"></i> Clear Search</button>';
    html += '</div>';

    if (data.results.length === 0) {
        html += '<p class="no-results">No results found.</p>';
    } else {
        html += '<table class="search-results-table">';
        html += '<thead><tr>';
        html += '<th style="width: 30px;"></th>';
        html += '<th>Case ID</th>';
        html += '<th>Type</th>';
        html += '<th>Species</th>';
        html += '<th>Breed</th>';
        html += '<th>Match</th>';
        html += '</tr></thead>';
        html += '<tbody>';

        data.results.forEach((result, index) => {
            const rowId = `result-row-${index}`;
            const expandId = `result-expand-${index}`;

            html += `<tr class="result-row" id="${rowId}" onclick="toggleResultExpand('${expandId}', '${rowId}')">`;
            html += '<td><i class="fas fa-chevron-right expand-icon"></i></td>';
            html += `<td><strong>${result.case_id || 'N/A'}</strong></td>`;
            html += `<td><span class="report-type-badge">${result.report_type || 'N/A'}</span></td>`;
            html += `<td>${result.species || 'N/A'}</td>`;
            html += `<td>${result.breed || 'N/A'}</td>`;
            html += `<td class="excerpt-cell">${result.excerpt}</td>`;
            html += '</tr>';

            // Expandable row for full document
            html += `<tr id="${expandId}" class="expanded-row" style="display:none;">`;
            html += '<td colspan="6">';
            html += '<div class="expanded-document">';
            html += buildDocumentView(result);
            html += '</div>';
            html += '</td></tr>';
        });

        html += '</tbody></table>';

        // Load More button
        if (data.has_more) {
            html += '<div class="load-more-container">';
            html += `<button class="load-more-btn" onclick="loadMoreSearchResults()">`;
            html += `<i class="fas fa-plus-circle"></i> Load More Results (${data.total_count - data.returned_count - data.skip} remaining)`;
            html += '</button>';
            html += '</div>';
        }
    }

    html += '</div>';

    resultsDiv.innerHTML = html;
}

function buildDocumentView(result) {
    let html = '<div class="document-view">';
    html += '<h6>Full Document Details</h6>';

    html += '<div class="document-section">';
    html += '<h7>Case Information</h7>';
    html += '<table class="document-table">';
    html += `<tr><td class="doc-label">Case ID:</td><td>${result.case_id || 'N/A'}</td></tr>`;
    html += `<tr><td class="doc-label">Report Type:</td><td>${result.report_type || 'N/A'}</td></tr>`;
    html += '</table>';
    html += '</div>';

    html += '<div class="document-section">';
    html += '<h7>Animal Details</h7>';
    html += '<table class="document-table">';
    html += `<tr><td class="doc-label">Species:</td><td>${result.species || 'N/A'}</td></tr>`;
    html += `<tr><td class="doc-label">Breed:</td><td>${result.breed || 'N/A'}</td></tr>`;
    html += `<tr><td class="doc-label">Age:</td><td>${result.age || 'N/A'}</td></tr>`;
    html += `<tr><td class="doc-label">Sex:</td><td>${result.sex || 'N/A'}</td></tr>`;
    html += '</table>';
    html += '</div>';

    if (result.diagnosis || result.tumor_type) {
        html += '<div class="document-section">';
        html += '<h7>Pathology</h7>';
        html += '<table class="document-table">';
        if (result.diagnosis) {
            const diagnosis = Array.isArray(result.diagnosis) ? result.diagnosis.join(', ') : result.diagnosis;
            html += `<tr><td class="doc-label">Diagnosis:</td><td>${diagnosis}</td></tr>`;
        }
        if (result.tumor_type) {
            html += `<tr><td class="doc-label">Tumor Type:</td><td>${result.tumor_type}</td></tr>`;
        }
        html += '</table>';
        html += '</div>';
    }

    // Full raw document (collapsible)
    html += '<div class="document-section">';
    html += '<details>';
    html += '<summary>View Raw JSON</summary>';
    html += '<pre class="json-display">' + JSON.stringify(result.full_document, null, 2) + '</pre>';
    html += '</details>';
    html += '</div>';

    html += '</div>';
    return html;
}

function toggleResultExpand(expandId, rowId) {
    const expandRow = document.getElementById(expandId);
    const mainRow = document.getElementById(rowId);
    const icon = mainRow.querySelector('.expand-icon');

    if (expandRow.style.display === 'none') {
        expandRow.style.display = 'table-row';
        icon.classList.remove('fa-chevron-right');
        icon.classList.add('fa-chevron-down');
        mainRow.classList.add('expanded');
    } else {
        expandRow.style.display = 'none';
        icon.classList.remove('fa-chevron-down');
        icon.classList.add('fa-chevron-right');
        mainRow.classList.remove('expanded');
    }
}

async function loadMoreSearchResults() {
    if (!currentSearchResults) return;

    currentSearchSkip += 50;

    const searchInput = document.getElementById('explorerSearchInput');
    const fieldFilter = document.getElementById('searchFieldFilter');

    try {
        const response = await fetch('/api/database-explorer/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: searchInput.value.trim(),
                field_filter: fieldFilter.value,
                skip: currentSearchSkip,
                limit: 50
            })
        });

        const data = await response.json();

        // Append new results to existing ones
        const tbody = document.querySelector('.search-results-table tbody');
        const loadMoreContainer = document.querySelector('.load-more-container');

        data.results.forEach((result, index) => {
            const globalIndex = currentSearchSkip + index;
            const rowId = `result-row-${globalIndex}`;
            const expandId = `result-expand-${globalIndex}`;

            let html = `<tr class="result-row" id="${rowId}" onclick="toggleResultExpand('${expandId}', '${rowId}')">`;
            html += '<td><i class="fas fa-chevron-right expand-icon"></i></td>';
            html += `<td><strong>${result.case_id || 'N/A'}</strong></td>`;
            html += `<td><span class="report-type-badge">${result.report_type || 'N/A'}</span></td>`;
            html += `<td>${result.species || 'N/A'}</td>`;
            html += `<td>${result.breed || 'N/A'}</td>`;
            html += `<td class="excerpt-cell">${result.excerpt}</td>`;
            html += '</tr>';

            html += `<tr id="${expandId}" class="expanded-row" style="display:none;">`;
            html += '<td colspan="6">';
            html += '<div class="expanded-document">';
            html += buildDocumentView(result);
            html += '</div>';
            html += '</td></tr>';

            tbody.innerHTML += html;
        });

        // Update result count
        const totalShown = currentSearchSkip + data.returned_count;
        document.querySelector('.result-count').textContent =
            `Showing ${totalShown} of ${data.total_count.toLocaleString()} results`;

        // Update or remove Load More button
        if (data.has_more) {
            loadMoreContainer.querySelector('.load-more-btn').innerHTML =
                `<i class="fas fa-plus-circle"></i> Load More Results (${data.total_count - totalShown} remaining)`;
        } else {
            loadMoreContainer.remove();
        }

    } catch (error) {
        console.error('Error loading more results:', error);
        alert('Error loading more results. Please try again.');
    }
}

function clearExplorerSearch() {
    document.getElementById('explorerSearchInput').value = '';
    document.getElementById('searchResults').style.display = 'none';
    document.getElementById('searchResults').innerHTML = '';
    document.getElementById('fieldDetails').style.display = 'block';
    currentSearchResults = null;
    currentSearchSkip = 0;
}
