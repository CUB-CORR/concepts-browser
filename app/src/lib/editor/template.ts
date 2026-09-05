/** Starter Python for a new config; the first and last lines are locked in the editor. */
export function pyTemplate(name: string): string {
	return `def ${name}(var, cohort):\n    # your code …\n    # Assign output to var.data\n    return var.data\n`;
}
