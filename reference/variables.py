"""Example python snippets for the sample reference dataset (see reference/vars.json).

On first boot the importer (api/importer.py) matches every top-level function here to the
variable of the same name in vars.json and stores its source as that variable's ``py``
snippet. The functions are illustrative — they are stored and displayed, never executed by
this service (evaluation happens in a separate package).
"""


def heart_rate(var, cohort):
    """Clean the extracted heart-rate series.

    Illustrative companion snippet to the vars.json definition: drops physiologically
    impossible readings and returns the modified series, which is merged back into the
    main dataframe.
    """
    series = cohort.df["heart_rate"]
    return series.where((series >= 0) & (series <= 300))
