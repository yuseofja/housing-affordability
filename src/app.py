# -*- coding: utf-8 -*-
"""
File:        app.py
Description: Creates a streamlit dashboard using the scraped housing data
Author:      Yuseof
Created:     2025-07-24
Modified:    2025-08-22
Usage:       --
"""

import math
import folium
import numpy as np
import pandas as pd
import geopandas as gpd
import streamlit as st
from pyairtable import Api
import branca.colormap as cm
from datetime import datetime
import streamlit.components.v1 as components
from config import (
    PATH_TO_ZIP_SHAPEFILE,
    HOUSE_TABLE_NAME,
    ZIP_TABLE_NAME,
    BASE_ID,
    AIRTABLE_ACCESS_TOKEN,
)

st.set_page_config(page_title="🏠 Housing Affordability Explorer")

#####################
# HELPERS AND CACHING
#####################

# NOTE: caching prevents lag and flickering in streamlit UI since results are stored rather than
# code rerunning / resources realoading every time


@st.cache_data
def load_zip_analysis():

    # load data
    api = Api(AIRTABLE_ACCESS_TOKEN)
    table = api.table(BASE_ID, ZIP_TABLE_NAME)
    rows = table.all()
    df = pd.json_normalize(r["fields"] for r in rows)

    # zip as str for join
    df["Zipcode"] = df["Zipcode"].astype(str).apply(lambda x: x.strip())

    # round PIR to one decimal
    df["PIR"] = df["PIR"].apply(lambda x: round(x, 1))

    # include formatted median income field for map viz
    df["Median_Price_Formatted"] = df["Median_Price"].apply(
        lambda x: "$" + format(int(x), ",")
    )

    # include formatted median home proce field for map viz
    df["Household_Median_Income_Formatted"] = df["Household_Median_Income"].apply(
        lambda x: "$" + format(int(x), ",")
    )

    return df


@st.cache_data
def load_house_listings():

    # load data
    api = Api(AIRTABLE_ACCESS_TOKEN)
    table = api.table(BASE_ID, HOUSE_TABLE_NAME)
    rows = table.all()
    df = pd.json_normalize(r["fields"] for r in rows)

    # fields for mapping
    df["Affordable_Color"] = np.where(df["Affordability_Gap"] < 0, "red", "green")
    df["Is_Affordable"] = np.where(df["Affordability_Gap"] < 0, False, True)

    return df


@st.cache_data
def load_zip_shapes(path=PATH_TO_ZIP_SHAPEFILE):

    # load data
    gdf = gpd.read_file(path)

    # remove any null geometries
    gdf = gdf[gdf["geometry"].notnull()].copy()

    # format zip col
    gdf.rename(columns={"GEOID20": "Zipcode"}, inplace=True)
    gdf["Zipcode"] = gdf["Zipcode"].astype(str)

    return gdf


###########
# LOAD DATA
###########

df_zip_analysis = load_zip_analysis()
df_house_analysis = load_house_listings()
gdf_zip_shapes = load_zip_shapes()

###############
# PREPROCESSING
###############

# merge zip affordability metrics with zip gdf
gdf_zip_analysis = df_zip_analysis.merge(gdf_zip_shapes, how="left", on="Zipcode")

# select only relevant columns
gdf_zip_map = gdf_zip_analysis[
    [
        "Zipcode",
        "PIR",
        "geometry",
        "Median_Price_Formatted",
        "Household_Median_Income_Formatted",
    ]
].copy()

geojson_map = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": {
                "Zipcode": row.Zipcode,
                "PIR": row.PIR,
                "Median_Price_Formatted": row.Median_Price_Formatted,
                "Household_Median_Income_Formatted": row.Household_Median_Income_Formatted,
            },
        }
        for idx, row in gdf_zip_map.iterrows()
        for geom in (
            [row.geometry]
            if row.geometry.geom_type != "MultiPolygon"
            else row.geometry.geoms
        )
    ],
}

##############
# STREAMLIT UI
##############

# ------- HEADER -------

st.title("🏠 Housing Affordability Explorer")
st.markdown(
    """
    <div style='text-align: center'>
    Visualizing the gap between affordable home prices and current market rates.<br>
    <div>
    """,
    unsafe_allow_html=True,
)
st.markdown("<br>", unsafe_allow_html=True)  # Add some vertical space
st.markdown("<div style='height:3px'></div>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["🗺 Map View", "📊 Charts", "📋 Data Table"])

# ------- FILTERS -------

# vertical spacing
st.sidebar.write("")
st.sidebar.write("")

st.sidebar.markdown("<h1 style='font-size:32px;'>Filters</h1>", unsafe_allow_html=True)

# vertical spacing
st.sidebar.write("")
st.sidebar.write("")

# house type filters
show_affordable = st.sidebar.checkbox("Show Affordable Homes", value=True)
show_unaffordable = st.sidebar.checkbox("Show Unaffordable Homes", value=True)

# vertical spacing
st.sidebar.write("")
st.sidebar.write("")

# house price filter
min_price, max_price = int(df_house_analysis.Price.min()), int(
    df_house_analysis.Price.max()
)
price_range = st.sidebar.slider(
    "Price Range",
    min_value=min_price,
    max_value=max_price,
    value=(min_price, max_price),
    step=10000,
    format="$%d",
)
# space
st.sidebar.write("")
st.sidebar.write("")

# zip filter
zip_options = sorted(df_zip_analysis["Zipcode"].unique().tolist())
selected_zips = st.sidebar.multiselect("Select Zipcode(s)", zip_options)

# ------- APPLY FILTERS -------

df_houses_filtered = df_house_analysis.copy()

try:
    # price filter
    df_houses_filtered = df_houses_filtered[
        (df_houses_filtered["Price"] >= price_range[0])
        & (df_houses_filtered["Price"] <= price_range[1])
    ]

    # zip filter
    if selected_zips:
        df_houses_filtered = df_houses_filtered[
            df_houses_filtered.Zipcode.isin([int(x) for x in selected_zips])
        ]

    if show_unaffordable == False:
        df_houses_filtered = df_houses_filtered[
            df_houses_filtered.Is_Affordable == True
        ]

    if show_affordable == False:
        df_houses_filtered = df_houses_filtered[
            df_houses_filtered.Is_Affordable == False
        ]

except:
    st.error("No Houses Match This Criteria...")

# --------- MAP ---------

# create folium map
map = folium.Map(location=[42.9159281, -78.7487142], zoom_start=11, tiles="CartoDB positron")

# Create a custom colormap (green → yellow → red)
colormap = cm.LinearColormap(
    colors=["green", "yellow", "red"],
    vmin=df_zip_analysis["PIR"].min(),
    vmax=8,  # NOTE!! This value is somewhat arbitrary, based on what is an "affordable" PIR from research
    caption="Price to Income Ratio (Affordability Measure)",
)

# add GeoJson layer with per-feature fill
folium.GeoJson(
    geojson_map,
    style_function=lambda feature: {
        "fillColor": colormap(feature["properties"]["PIR"]),
        "color": "black",
        "weight": 0.5,
        "fillOpacity": 0.7,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=[
            "Zipcode",
            "PIR",
            "Median_Price_Formatted",
            "Household_Median_Income_Formatted",
        ],
        aliases=[
            "Zipcode",
            "Price to Income Ratio",
            "Median House Price",
            "Median Income",
        ],
    ),
).add_to(map)

# add colormap legend
colormap.add_to(map)

# Add house pins
for _, row in df_houses_filtered.iterrows():
    folium.Marker( 
        location=[row["Lat"], row["Lng"]],
        tooltip=( 
             f"<b>{row['Address']}</b><br>" 
             f"<div style='line-height:2'></div>" 
             f"<b><i>Price:</i></b> ${int(row['Price']):,}<br>" 
             f"<b><i>Affordable Price:</i></b> ${int(row['Affordable_Price']):,}<br>" 
             f"<b><i>Affordability Gap:</i></b> ${int(row['Affordability_Gap']):,}" 
        ),
        icon=folium.Icon(
            color=row["Affordable_Color"],
            icon=folium.CustomIcon( icon_image="home", icon_size=(5,5) ),
            prefix="fa"),
).add_to(map)

# show map in streamlit
with tab1:

    try:
        # kpi columns
        col1, col2, col3, col4 = st.columns([1.5, 2, 2, 1])
        col1.metric("Total Homes", len(df_houses_filtered))
        col2.metric(
            "Median Home Price", f"${int(df_houses_filtered['Price'].median()):,}"
        )
        col3.metric(
            "Median Affordability Gap",
            f"${int(df_houses_filtered['Affordability_Gap'].median()):,}",
        )
        col4.metric(
            "% Affordable",
            f"{math.trunc((len(df_houses_filtered[df_houses_filtered.Affordability_Gap == 0]) / len(df_houses_filtered)) * 100)}%",
        )

    except:
        st.error("No Houses Match This Criteria...")

    # space between header and map
    st.empty()

    # render folium map HTML and embed it into a fixed-height iframe so Streamlit reserves that space up-front.
    # this both fixes issue of summary cards being sent to bottom of page, and screen flickering.
    map_html = map.get_root().render()
    components.html(map_html, height=650, scrolling=False)

    # space between map and summary cards
    st.empty()

    # summary cols
    most_aff, least_aff = st.columns(2)

    with most_aff:

        # least affordable neighborhoods (Recc: These neighborhoods Need pricing support)
        df_most_aff = df_zip_analysis.sort_values("PIR").head(3)[["Zipcode", "PIR"]]

        insights_html = """
        <div style="
            padding:15px;
            background-color:#007506;
            border-radius:10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            color: white;
        ">
            <h4 style="margin-top:0;">⬆️ Most Affordable Areas</h4>
            <ul style="padding-left:20px; margin:0;">
        """

        for _, row in df_most_aff.iterrows():
            insights_html += f"<li><b>{row.Zipcode}</b> — Price to Income Ratio = {row.PIR:,.1f}</li>"

        insights_html += """
            </ul>
        </div>
        """

        st.markdown(insights_html, unsafe_allow_html=True)

    with least_aff:

        # least affordable neighborhoods (Recc: These neighborhoods Need pricing support)
        df_least_aff = df_zip_analysis.sort_values("PIR").tail(3)[["Zipcode", "PIR"]]

        insights_html = """
        <div style="
            padding:15px;
            background-color:#B30000;
            border-radius:10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            color: white;
        ">
            <h4 style="margin-top:0;">⬇️ Least Affordable Areas</h4>
            <ul style="padding-left:20px; margin:0;">
        """

        for _, row in df_least_aff.iterrows():
            insights_html += f"<li><b>{row.Zipcode}</b> — Price to Income Ratio = {row.PIR:,.1f}</li>"

        insights_html += """
            </ul>
        </div>
        """

        st.markdown(insights_html, unsafe_allow_html=True)

    # padding under summary cards
    st.markdown("</div>", unsafe_allow_html=True)

    # ------- MAP FOOTER -------

    with st.expander("ℹ️ About this dashboard"):
        st.markdown(
            """
        Affordability is determined using the median household income of each zipcode (sourced from US Census). 
    
        - **Affordable Price** = Zipcode Median Income x 3
        - **Affordability Gap** = House Price - Affordable Price (Value of $0 indicates house is affordable)
        - **Price to Income Ratio (PIR)** = Zipcode Median House Price / Zipcode Median Income
        - **Red Pins** indicate unaffordable homes.
        - **Green Pins** indicate affordable homes.
        """
        )

    # Display last refreshed timestamp at top of page
    last_updated = df_house_analysis["Created"].iloc[0][:-5]
    last_updated = last_updated.replace("T", " ")
    last_updated = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S").strftime(
        "%m/%d/%y - %I:%M %p"
    )
    st.markdown(
        f"""
                <div style='text-align: right'>
                    🕒 <b>Data Last Updated:</b> {last_updated}
                </div>
                """,
        unsafe_allow_html=True,
    )

# --------- CHARTS ---------

with tab2:
    st.markdown(
        """
        <div style='text-align: center; padding: 50px; font-size: 24px; font-weight: bold; color: gray;'>
            🚧 Charts Coming Soon 🚧
        </div>
        """,
        unsafe_allow_html=True,
    )

# --------- DATA TABLE ---------

with tab3:
    st.markdown(
        """
        <div style='text-align: center; padding: 50px; font-size: 24px; font-weight: bold; color: gray;'>
            🚧 Data Table Coming Soon 🚧
        </div>
        """,
        unsafe_allow_html=True,
    )
