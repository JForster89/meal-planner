import sqlite3
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Database setup
def init_db():
    with sqlite3.connect('recipes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cooking_time TEXT,
                servings INTEGER,
                ingredients TEXT NOT NULL,
                instructions TEXT NOT NULL
            )
        ''')
    conn.close()

init_db()

@app.route('/')
def home():
    return "Welcome to the Hello Fresh Recipe Manager!"

@app.route('/recipes')
def view_recipes():
    with sqlite3.connect('recipes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, cooking_time, servings, ingredients, instructions FROM recipes')
        recipes = [
            {
                "id": row[0],
                "name": row[1],
                "cooking_time": row[2],
                "servings": row[3],
                "ingredients": row[4].split(';'),
                "instructions": row[5].split(';')
            }
            for row in cursor.fetchall()
        ]
    return render_template('recipes.html', recipes=recipes)

@app.route('/add', methods=['GET', 'POST'])
def add_recipe():
    if request.method == 'POST':
        # Get form data
        name = request.form['name']
        cooking_time = request.form.get('cooking_time', '')
        servings = request.form.get('servings', 1)

        # Process ingredients
        ingredient_amounts = request.form.getlist('ingredient_amount[]')
        ingredient_units = request.form.getlist('ingredient_unit[]')
        ingredient_names = request.form.getlist('ingredient_name[]')
        ingredients = [
            f"{amount} {unit} {name}".strip()
            for amount, unit, name in zip(ingredient_amounts, ingredient_units, ingredient_names)
            if name
        ]
        ingredients_str = ';'.join(ingredients)

        # Process instructions
        instructions = request.form.getlist('instruction[]')
        instructions_str = ';'.join(instructions)

        # Insert into the database
        with sqlite3.connect('recipes.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO recipes (name, cooking_time, servings, ingredients, instructions)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, cooking_time, servings, ingredients_str, instructions_str))
            conn.commit()

        return redirect(url_for('view_recipes'))

    return render_template('add_recipe.html')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_recipe(id):
    with sqlite3.connect('recipes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT name, cooking_time, servings, ingredients, instructions FROM recipes WHERE id = ?', (id,))
        recipe = cursor.fetchone()

    if not recipe:
        return "Recipe not found!", 404

    if request.method == 'POST':
        name = request.form['name']
        cooking_time = request.form.get('cooking_time', '')
        servings = request.form.get('servings', 1)

        # Process ingredients
        ingredient_amounts = request.form.getlist('ingredient_amount[]')
        ingredient_units = request.form.getlist('ingredient_unit[]')
        ingredient_names = request.form.getlist('ingredient_name[]')
        ingredients = [
            f"{amount} {unit} {name}".strip()
            for amount, unit, name in zip(ingredient_amounts, ingredient_units, ingredient_names)
            if name
        ]
        ingredients_str = ';'.join(ingredients)

        # Process instructions
        instructions = request.form.getlist('instruction[]')
        instructions_str = ';'.join(instructions)

        with sqlite3.connect('recipes.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE recipes
                SET name = ?, cooking_time = ?, servings = ?, ingredients = ?, instructions = ?
                WHERE id = ?
            ''', (name, cooking_time, servings, ingredients_str, instructions_str, id))
            conn.commit()

        return redirect(url_for('view_recipes'))

    recipe_data = {
        "id": id,
        "name": recipe[0],
        "cooking_time": recipe[1],
        "servings": recipe[2],
        "ingredients": recipe[3].split(';'),
        "instructions": recipe[4].split(';')
    }
    return render_template('edit_recipe.html', recipe=recipe_data)

@app.route('/delete/<int:id>', methods=['GET'])
def delete_recipe(id):
    with sqlite3.connect('recipes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM recipes WHERE id = ?', (id,))
        conn.commit()
    return redirect(url_for('view_recipes'))

if __name__ == '__main__':
    app.run(debug=True)
