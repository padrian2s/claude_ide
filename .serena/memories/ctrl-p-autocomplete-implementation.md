# Ctrl+P Quick Input - Autocomplete & History Implementation

## Cerințe

1. **TextArea multiline** cu soft wrap pentru text lung
2. **Autocomplete** poziționat exact sub cuvântul curent (nu în status bar)
3. **History navigation** cu Ctrl+O (prev) și Ctrl+L (next)
4. **History wrapped** - textul din history să fie afișat complet, nu tăiat
5. **Nu există race condition** între autocomplete și history

## Problema Tehnică

Când TextArea are `soft_wrap=True`, textul se întinde pe mai multe rânduri vizuale, dar `cursor_location` returnează poziția logică (rând logic, coloană). 

Dacă poziționăm overlay-ul autocomplete la `row + 1`, acesta apare în locul greșit pentru că `row` e rândul logic, nu vizual.

## Soluția

### 1. Calculul Rândului Vizual

```python
# Obține lățimea TextArea
width = ta.size.width - 1

# Calculează rândurile vizuale pentru liniile anterioare
visual_row = 0
for i in range(row):
    line_len = len(lines[i])
    # Fiecare linie ocupă cel puțin 1 rând vizual
    # Liniile lungi ocupă (line_len + width - 1) // width rânduri
    visual_row += max(1, (line_len + width - 1) // width) if width > 0 else 1

# Adaugă rândurile vizuale din linia curentă până la cursor
visual_row += col // width if width > 0 else 0
```

### 2. Calculul Coloanei Vizuale

```python
# Coloana vizuală e restul împărțirii la lățime
visual_col = col % width if width > 0 else col

# Padding pentru poziționare orizontală
padding = " " * (visual_col + 1)
```

### 3. Poziționarea Overlay-ului

```python
auto.update(f"{padding}{self.suggestion}")
auto.styles.offset = (0, visual_row + 1)
auto.styles.display = "block"
```

### 4. Ascunderea Completă când nu e nevoie

```python
auto.update("")
auto.styles.display = "none"
```

## CSS Layers

```css
Screen { layers: base overlay; }
#input { layer: base; }
#autocomplete {
    layer: overlay;
    background: transparent;
    height: 1;
    width: 100%;
}
#status { layer: base; }
```

## History Navigation

- **Ctrl+O**: History anterior (mai vechi)
- **Ctrl+L**: History următor (mai nou)
- Binding-uri pe App level, nu pe TextArea (TextArea consumă Up/Down)

### Prevenirea Reset-ului hist_idx

În `on_text_area_changed`, verificăm dacă textul s-a schimbat față de history-ul curent:

```python
if self.hist_idx >= 0:
    current_hist = self.history[-(self.hist_idx + 1)]
    if event.text_area.text != current_hist:
        self.hist_idx = -1
        ta.remove_class("history")
```

## Fișiere Modificate

- `quick_input.py` - QuickInputApp class

## Shortcuts

| Key | Action |
|-----|--------|
| Ctrl+O | History prev |
| Ctrl+L | History next |
| Tab | Complete suggestion |
| Ctrl+S | Send to F1 |
| Ctrl+G | AI enhance |
| Esc | Quit |
