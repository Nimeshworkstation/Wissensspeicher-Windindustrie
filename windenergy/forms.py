from django import forms

from windenergy.models import QuerySuggestion


class QuerySuggestionForm(forms.ModelForm):
    class Meta:
        model = QuerySuggestion
        fields = ("question", "details")
        widgets = {
            "question": forms.TextInput(attrs={
                "maxlength": 500,
                "placeholder": "z. B. Wie viele Anlagen laufen 2028 aus der EEG-Förderung?",
            }),
            "details": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Welche Region, welcher Zeitraum oder welche Kennzahlen sind gemeint?",
            }),
        }
