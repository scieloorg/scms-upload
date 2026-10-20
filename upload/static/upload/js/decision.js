(() => {
    const CORRECTION = 'pending-correction';
    const REVIEW = 'pending-qa-decision';
    const PUBLICATION = new Set(['ready-to-preview', 'ready-to-publish']);

    class DecisionController extends window.StimulusModule.Controller {
        static targets = ['action', 'reviewer', 'corrections', 'comment', 'publication'];

        connect() {
            this.refresh();
        }

        refresh() {
            const action = this.actionTarget.value;
            this.setVisible(this.reviewerTarget, action === REVIEW);
            this.setVisible(this.correctionsTarget, action === CORRECTION);
            this.setVisible(this.commentTarget, Boolean(action));
            this.setVisible(this.publicationTarget, PUBLICATION.has(action));
            this.reviewerTarget.querySelector('select').required = action === REVIEW;
            this.correctionsTarget.querySelector('select').required = action === CORRECTION;
            this.commentTarget.querySelector('textarea').required = action === CORRECTION;
        }

        setVisible(panel, visible) {
            panel.hidden = !visible;
            panel.querySelectorAll('input, select, textarea, button').forEach((field) => {
                field.disabled = !visible;
            });
        }
    }

    window.wagtail.app.register('upload-decision', DecisionController);
})();
