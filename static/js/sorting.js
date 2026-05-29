// Sorting functionality
let currentSortColumn = '';
let currentSortDirection = 'asc';

function sortTable(column) {
    const headers = document.querySelectorAll('th');
    headers.forEach(header => {
        header.classList.remove('sort-asc', 'sort-desc');
    });

    if (currentSortColumn === column) {
        currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = column;
        currentSortDirection = 'asc';
    }

    const header = document.querySelector(`th:nth-child(${getColumnIndex(column) + 1})`);
    header.classList.add(`sort-${currentSortDirection}`);

    currentResults.sort((a, b) => {
        let valueA = getValueForColumn(a, column);
        let valueB = getValueForColumn(b, column);

        if (typeof valueA === 'string') {
            valueA = valueA.toLowerCase();
            valueB = valueB.toLowerCase();
        }

        if (valueA < valueB) return currentSortDirection === 'asc' ? -1 : 1;
        if (valueA > valueB) return currentSortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    displayAiSearchResults(currentResults);
}

function getColumnIndex(column) {
    const columns = ['score', 'case_id', 'species', 'date', 'pathologist', 'report_type'];
    return columns.indexOf(column);
}

function getValueForColumn(result, column) {
    const data = result.data || {};
    const animal = data.animal_details || {};
    const report = data.report_metadata || {};
    const histo = data.histopathology || {};

    switch(column) {
        case 'score':
            return result.score || 0;
        case 'case_id':
            // Format-agnostic sort key: zero-pad so IDs sort naturally
            // regardless of the institution's numbering scheme.
            return (result.case_id || '').padStart(8, '0');
        case 'species':
            return animal.species || '';
        case 'date':
            return report.date_received || '';
        case 'diagnosis':
            return histo.diagnosis || '';
        case 'pathologist':
            return (report.pathologists || []).join(', ');
        default:
            return '';
    }
}
