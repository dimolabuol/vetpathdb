// Export functionality
function exportToCSV() {
    if (!currentResults || currentResults.length === 0) return;

    // Detect if results came from AI search (have score field)
    const isAISearch = currentResults[0] && currentResults[0].score !== undefined;
    const isSemanticOnly = window.semanticOnly;

    let headers, rows;

    if (isAISearch) {
        // AI search mode — mirror the on-screen table columns
        const lastCol = isSemanticOnly ? 'Summary' : 'AI Analysis';
        headers = ['Match Score', 'Case ID', 'Species', 'Breed', 'Date', 'Pathologist', 'Report Type', lastCol];

        rows = currentResults.map(r => {
            const data = r.data || {};
            const animal = data.animal_details || {};
            const report = data.report_metadata || {};
            const lastValue = isSemanticOnly
                ? (data.summary || data.comment || 'N/A')
                : (r.reasoning || 'No AI analysis available');

            return [
                r.score != null ? r.score.toFixed(2) : 'N/A',
                r.case_id || '',
                animal.species || 'N/A',
                animal.breed || 'N/A',
                report.date_received || '',
                (report.pathologists || []).join(', '),
                report.report_type || 'N/A',
                lastValue
            ];
        });
    } else {
        // Normal search mode
        headers = ['Case ID', 'Species', 'Breed', 'Date', 'Pathologist', 'Report Type', 'Summary', 'Comment'];

        rows = currentResults.map(r => {
            const data = r.data || {};
            const animal = data.animal_details || {};
            const report = data.report_metadata || {};

            return [
                r.case_id || '',
                animal.species || 'N/A',
                animal.breed || 'N/A',
                report.date_received || '',
                (report.pathologists || []).join(', '),
                report.report_type || 'N/A',
                data.summary || report.summary || 'N/A',
                data.comment || report.comment || 'N/A'
            ];
        });
    }
    
    const csvContent = [
        headers.join(','),
        ...rows.map(row => row.map(cell => `"${cell.replace(/"/g, '""')}"`).join(','))
    ].join('\n');
    
    downloadCSV(csvContent);
}

function downloadCSV(csvContent) {
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `search_results_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}
