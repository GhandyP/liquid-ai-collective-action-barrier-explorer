# External evidence sources: EU election abstention

This folder records provenance for a bounded, manually prepared real-evidence example. The app uses `data/curated_cases.json`; it does not parse or submit the local source PDFs or archive. The prototype keeps the two source streams distinct because they differ in method and collection date.

## Curated case and source streams

`data/curated_cases.json` contains one structured case prepared from selected, paraphrased findings in two published European Parliament reports:

- **2009 post-electoral survey:** Special Eurobarometer 320 / Wave 71.3. The report covers the post-election survey conducted in June–July 2009. The curated record uses the reported reasons for non-voting (QK4b, p. 27), not respondent-level records; it does not rely on a report-wide interview total as the item denominator.
  Source: https://www.europarl.europa.eu/pdf/eurobarometre/28_07/EB71.3_post-electoral_final_report_EN.pdf
- **2012 abstention focus groups:** *‘Impulsive’ and ‘Unspecified’ Abstainers: Voting Barriers and Incentives*. Fieldwork took place 6–17 February 2012; the report describes three groups per EU Member State, with 8–12 participants per group, and says the groups are not representative of the whole population. The curated record paraphrases themes and includes no raw quotations or participant-level data.
  Source: https://www.europarl.europa.eu/pdf/eurobarometre/2012/research/121126_EurobarometerQualitativeStudy_Abstainers_EN.pdf

The survey percentages are rounded reported values for respondents who did not vote; this base is reported as 57% of the total sample. Up to three answers were allowed, so the percentages are not expected to sum to 100%. The source facts retained for this case do not give a respondent count for that base, and no count is inferred from the report's overall interview count. The survey and focus-group records remain separate: they are from different years, methods, and samples.

## Broader local archive inventory

`data/external/archive/` and `data/external/archive.zip` retain a broader local collection, including country-level voter and abstainer profile fiches, related reports, metadata, and archive bundles. These materials are provenance/reference material, not additional app inputs. The app uses a bounded structured case rather than blindly sending every PDF: the reports cover different populations, methods, and time points, and the archive's volume and country-specific detail would make an undifferentiated provider payload difficult to interpret or validate. The curated record instead retains selected summaries, reported percentages, source references, and limitations.

The raw local reports and archives remain ignored by Git. The tracked structured case is not a transcription or exhaustive extraction of those documents. It is also not a respondent-row dataset or a common sample combining the two studies.

## Use and limitations

- Keep the 2009 survey and 2012 focus groups as distinct evidence streams; they are not the same participant sample or time point.
- Preserve the source method, year, citation, known population/base, and limitations. For the curated survey percentages, do not invent counts or normalize the rounded multi-select distribution to 100%.
- Focus-group findings are exploratory and non-representative. Survey associations and self-reported reasons do not establish the cause of an individual's abstention.
- These PDFs are published reports, not raw survey-response rows or verbatim focus-group transcripts.
- The app's outputs are hypotheses for human review, not causes or individual judgments. Do not use them to profile individuals.

## Reuse

The European Parliament's general legal notice says reuse of relevant EU-owned material is generally permitted when the complete item is reproduced and the source is acknowledged, subject to any item-specific conditions. Check each report's own notice and applicable conditions before redistribution; the project does not grant rights to source material.
Legal notice: https://www.europarl.europa.eu/legal-notice/en/

The PDF and archive files are local external data and are ignored by Git pending a separate publication/licensing decision. This README and the bounded structured case record provenance without reproducing raw report text.

Related Kaggle listing: https://www.kaggle.com/datasets/eu-parliament/voting-behaviour-survey-2009-european-elections
