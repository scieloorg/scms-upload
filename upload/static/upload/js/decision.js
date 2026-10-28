(() => {
    const CORRECTION = 'pending-correction';
    const PUBLICATION = new Set(['ready-to-preview', 'ready-to-publish']);

    class DecisionController extends window.StimulusModule.Controller {
        static targets = ['action', 'corrections', 'comment', 'publication'];

        connect() {
            this.refresh();
        }

        refresh() {
            const action = this.actionTarget.value;
            this.setVisible(this.correctionsTarget, action === CORRECTION);
            this.setVisible(this.commentTarget, Boolean(action));
            this.setVisible(this.publicationTarget, PUBLICATION.has(action));
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
