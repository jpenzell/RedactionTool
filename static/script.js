document.addEventListener('DOMContentLoaded', function() {
    const previewButton = document.getElementById('previewButton');
    const previewModal = document.getElementById('previewModal');
    const closeButton = document.querySelector('.close');

    // Handle preview button click
    if (previewButton) {
        previewButton.addEventListener('click', function(e) {
            e.preventDefault();
            const formData = new FormData(document.getElementById('redactionForm'));

            fetch('/preview', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    alert(data.error);
                } else {
                    displayPreview(data.preview);
                    previewModal.style.display = 'block';
                }
            })
            .catch(error => {
                console.error('Error:', error);
            });
        });
    }

    // Handle modal close button
    if (closeButton) {
        closeButton.addEventListener('click', function() {
            previewModal.style.display = 'none';
        });
    }

    // Display the preview content
    function displayPreview(preview) {
        const previewContent = document.getElementById('previewContent');
        previewContent.innerHTML = preview.replace(/\n/g, '<br>');
    }

    // Toggle custom input fields
    document.addEventListener('change', function(event) {
        if (event.target.matches('select[name^="redact_"]')) {
            toggleCustomInput(event.target);
        }
    });

    function toggleCustomInput(select) {
        const customInput = select.nextElementSibling;
        if (customInput && customInput.classList.contains('custom-input')) {
            customInput.style.display = select.value === 'CUSTOM' ? 'inline-block' : 'none';
        }
    }

    function applyToGroup(groupSelect, groupType) {
        const items = document.querySelectorAll(`[name^="redact_"]`);
        items.forEach(function(item) {
            if (item.name.startsWith('redact_') && item.closest('.redaction-group').querySelector('h3').textContent === groupType) {
                item.value = groupSelect.value;
                toggleCustomInput(item);
            }
        });
    }

    // Inline redaction adjustments
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('redacted-term')) {
            let originalTerm = event.target.getAttribute('data-original');
            let newAction = prompt(`Edit action for ${originalTerm}: (ignore/redact/mask/custom)`);
            if (newAction) {
                updateRedaction(originalTerm, newAction);
            }
        }
    });

    function updateRedaction(term, action) {
        // Simulate an AJAX call to update the redaction map on the server
        fetch('/update_redaction', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ term: term, action: action })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(`Redaction updated for term: ${term}. Action: ${action}`);
                location.reload(); // Refresh to show updated redactions
            } else {
                alert('Failed to update redaction.');
            }
        })
        .catch(error => {
            console.error('Error updating redaction:', error);
            alert('Error updating redaction.');
        });
    }

    // Other functionalities like adding terms
    let termCount = 0;
    const maxTerms = 3;
    const addTermButton = document.getElementById('addTerm');
    const additionalTermsDiv = document.getElementById('additionalTerms');
    
    if (addTermButton) {
        addTermButton.addEventListener('click', function() {
            if (termCount < maxTerms) {
                termCount++;
                const newTermDiv = document.createElement('div');
                newTermDiv.className = 'form-group';
                newTermDiv.innerHTML = `
                    <label for="additional_term_${termCount}">Additional Term ${termCount}:</label>
                    <input type="text" name="additional_term_${termCount}" id="additional_term_${termCount}">
                    <label for="additional_replacement_${termCount}">Replacement:</label>
                    <input type="text" name="additional_replacement_${termCount}" id="additional_replacement_${termCount}">
                `;
                additionalTermsDiv.appendChild(newTermDiv);

                if (termCount === maxTerms) {
                    addTermButton.style.display = 'none';
                }
            }
        });
    }

    window.applyToGroup = applyToGroup;
    window.toggleCustomInput = toggleCustomInput;
});
