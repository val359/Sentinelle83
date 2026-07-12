#!/usr/bin/env python3

from __future__ import annotations

import math
from datetime import datetime

import requests
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from sentinelle83.app import (
    analyze,
    init_db,
    load_config,
    parse_html,
    parse_rss,
)

console = Console()


def direction_vent(degres):
    directions = [
        "Nord",
        "Nord-Est",
        "Est",
        "Sud-Est",
        "Sud",
        "Sud-Ouest",
        "Ouest",
        "Nord-Ouest",
    ]

    try:
        return directions[round(float(degres) / 45) % 8]
    except (TypeError, ValueError):
        return "Inconnue"


def recuperer_meteo():
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": 43.4332,
        "longitude": 6.7356,
        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "wind_gusts_10m,"
            "precipitation"
        ),
        "wind_speed_unit": "kmh",
        "timezone": "Europe/Paris",
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    return response.json().get("current", {})


def niveau_meteo(meteo):
    temperature = float(meteo.get("temperature_2m") or 0)
    humidite = float(meteo.get("relative_humidity_2m") or 100)
    vent = float(meteo.get("wind_speed_10m") or 0)
    rafales = float(meteo.get("wind_gusts_10m") or 0)

    score = 0

    if temperature >= 30:
        score += 1

    if temperature >= 35:
        score += 1

    if humidite <= 40:
        score += 1

    if humidite <= 25:
        score += 1

    if vent >= 30:
        score += 1

    if rafales >= 50:
        score += 1

    if score >= 5:
        return "Très élevé", "bold red"

    if score >= 3:
        return "Élevé", "bold yellow"

    if score >= 1:
        return "Modéré", "yellow"

    return "Faible", "green"


def barre(valeur, maximum, largeur=24):
    try:
        valeur = max(0.0, min(float(valeur), float(maximum)))
    except (TypeError, ValueError):
        valeur = 0

    rempli = round((valeur / maximum) * largeur)
    return "█" * rempli + "░" * (largeur - rempli)


def afficher_meteo():
    try:
        meteo = recuperer_meteo()
    except Exception as erreur:
        console.print(
            Panel(
                f"[red]Météo indisponible :[/red] {erreur}",
                title="🌤️ Météo de Fréjus",
            )
        )
        return

    temperature = meteo.get("temperature_2m", "?")
    humidite = meteo.get("relative_humidity_2m", "?")
    vent = meteo.get("wind_speed_10m", "?")
    rafales = meteo.get("wind_gusts_10m", "?")
    direction = direction_vent(meteo.get("wind_direction_10m"))
    pluie = meteo.get("precipitation", "?")

    niveau, style = niveau_meteo(meteo)

    table = Table(box=box.ROUNDED, show_header=False, expand=True)
    table.add_column("Mesure", style="cyan", width=20)
    table.add_column("Valeur", style="white")
    table.add_column("Graphique", style="blue")

    table.add_row(
        "🌡️ Température",
        f"{temperature} °C",
        barre(temperature, 45),
    )

    table.add_row(
        "💧 Humidité",
        f"{humidite} %",
        barre(humidite, 100),
    )

    table.add_row(
        "🌬️ Vent",
        f"{vent} km/h — {direction}",
        barre(vent, 80),
    )

    table.add_row(
        "💨 Rafales",
        f"{rafales} km/h",
        barre(rafales, 120),
    )

    table.add_row(
        "🌧️ Précipitations",
        f"{pluie} mm",
        barre(pluie, 20),
    )

    table.add_row(
        "🔥 Contexte incendie",
        Text(niveau, style=style),
        "",
    )

    console.print(
        Panel(
            table,
            title="🌤️ Météo actuelle à Fréjus",
            subtitle=f"Mise à jour : {meteo.get('time', 'inconnue')}",
            border_style="cyan",
        )
    )


def lire_source(source):
    if source.get("type") == "rss":
        return parse_rss(source)

    return parse_html(source)


def afficher_controle():
    config = load_config()
    connexion = init_db()

    table = Table(
        title="📡 Contrôle des sources",
        box=box.ROUNDED,
        expand=True,
    )

    table.add_column("Source", style="cyan")
    table.add_column("État", justify="center")
    table.add_column("Articles", justify="right")
    table.add_column("Alertes", justify="right")
    table.add_column("Graphique")

    total_articles = 0
    total_alertes = 0

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            table.add_row(
                source.get("name", "Source"),
                "[yellow]Désactivée[/yellow]",
                "0",
                "0",
                "",
            )
            continue

        try:
            items = lire_source(source)
            alertes = [
                item
                for item in items
                if analyze(item, config) is not None
            ]

            nombre_articles = len(items)
            nombre_alertes = len(alertes)

            total_articles += nombre_articles
            total_alertes += nombre_alertes

            table.add_row(
                source["name"],
                "[green]● OK[/green]",
                str(nombre_articles),
                (
                    f"[bold red]{nombre_alertes}[/bold red]"
                    if nombre_alertes
                    else "[green]0[/green]"
                ),
                barre(nombre_articles, 40, 18),
            )

        except Exception as erreur:
            table.add_row(
                source.get("name", "Source"),
                "[red]● Erreur[/red]",
                "—",
                "—",
                "[red]indisponible[/red]",
            )

            console.print(
                f"[dim red]{source.get('name')} : {erreur}[/dim red]"
            )

    console.print(table)

    resume = Table(box=box.SIMPLE, show_header=False, expand=True)
    resume.add_column("Information", style="cyan")
    resume.add_column("Valeur", justify="right")

    resume.add_row("Articles analysés", str(total_articles))
    resume.add_row(
        "Alertes potentielles",
        (
            f"[bold red]{total_alertes}[/bold red]"
            if total_alertes
            else "[green]0[/green]"
        ),
    )
    resume.add_row(
        "Rayon surveillé",
        f"{config.get('alert_radius_km', '?')} km autour de Fréjus",
    )
    resume.add_row(
        "Heure du contrôle",
        datetime.now().strftime("%d/%m/%Y à %H:%M:%S"),
    )

    console.print(
        Panel(
            resume,
            title="📊 Résumé",
            border_style="green" if total_alertes == 0 else "red",
        )
    )

    connexion.close()


def main():
    console.clear()

    titre = Text()
    titre.append("🚒 SENTINELLE83\n", style="bold red")
    titre.append(
        "Veille incendie locale autour de Fréjus",
        style="bold white",
    )

    console.print(
        Panel(
            titre,
            border_style="red",
            padding=(1, 2),
        )
    )

    afficher_meteo()
    afficher_controle()

    console.print(
        "\n[dim]Ce programme complète les informations officielles. "
        "En cas d’urgence : 18 ou 112.[/dim]"
    )


if __name__ == "__main__":
    main()
