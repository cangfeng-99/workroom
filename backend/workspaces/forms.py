from django import forms


class NewFileForm(forms.Form):
    """Name and text for one new demo file; bytes are limited by the service."""

    name = forms.CharField(label='文件名', max_length=255, strip=False)
    content = forms.CharField(
        label='文件内容',
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={'rows': 8}),
    )
