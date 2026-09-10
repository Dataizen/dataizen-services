"""DATEX II v3 XML writer for the canonical TrafficObservation model.

Produces a payloadPublication of MeasuredDataPublication shape, with
one siteMeasurements element per canonical record. KPIs are mapped
to DATEX II basicData where a clean equivalent exists, and to
extensible auxiliary elements otherwise.

This output is a *structural projection*: element names and the
overall payload skeleton follow the DATEX II spec, but the
document is not claimed to be fully schema-validated against the
DATEX II XSDs. The intent is to make round-tripping with a real
DATEX II consumer obvious and to demonstrate that DATEX II and
Smart Data Models JSON-LD can be derived from one canonical pivot.
"""
from __future__ import annotations
from typing import Iterable
from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace
from xml.dom import minidom

from .model import TrafficObservation


DATEX2_NS = "http://datex2.eu/schema/3/3.0"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

register_namespace("", DATEX2_NS)
register_namespace("xsi", XSI_NS)


XSI_TYPE = f"{{{XSI_NS}}}type"


def _e(parent, tag, text=None, attribs=None, **kwattrs):
    """Create a SubElement in the DATEX II namespace, with optional text and attribs."""
    attrs = dict(attribs or {})
    attrs.update(kwattrs)
    el = SubElement(parent, f"{{{DATEX2_NS}}}{tag}", attrs)
    if text is not None:
        el.text = str(text)
    return el


def _site_measurements(parent, obs: TrafficObservation, index: int) -> None:
    site = _e(parent, "siteMeasurements")
    _e(site, "measurementSiteReference", id=f"{obs.city.countryCode}-{obs.city.name}-aggregate", version="1.0")
    _e(site, "measurementTimeDefault", text=obs.observedAt)

    mv_idx = 1
    if obs.travelTimePer10kmMin is not None:
        mv = _e(site, "measuredValue", index=str(mv_idx))
        bd = _e(mv, "basicData", attribs={XSI_TYPE: "TravelTimeValue"})
        tt = _e(bd, "travelTime")
        _e(tt, "duration", text=f"PT{int(obs.travelTimePer10kmMin*60)}S")
        _e(tt, "perDistance", text="10")
        _e(tt, "distanceUnit", text="KILOMETRES")
        mv_idx += 1

    if obs.jamsLengthKm is not None:
        mv = _e(site, "measuredValue", index=str(mv_idx))
        bd = _e(mv, "basicData", attribs={XSI_TYPE: "TrafficConcentration"})
        _e(bd, "concentrationOfTrafficLengthInKilometres", text=str(obs.jamsLengthKm))
        mv_idx += 1

    if obs.jamsCount is not None:
        mv = _e(site, "measuredValue", index=str(mv_idx))
        bd = _e(mv, "basicData", attribs={XSI_TYPE: "NumberOfIncidents"})
        _e(bd, "numberOfQueues", text=str(obs.jamsCount))
        mv_idx += 1

    if obs.delayMin is not None:
        mv = _e(site, "measuredValue", index=str(mv_idx))
        bd = _e(mv, "basicData", attribs={XSI_TYPE: "DelayValue"})
        _e(bd, "delay", text=f"PT{int(obs.delayMin*60)}S")
        mv_idx += 1

    # Provider-specific extensions outside the strict DATEX II schema
    if obs.trafficIndex is not None:
        _e(site, "trafficIndexLive", text=str(obs.trafficIndex))
    if obs.trafficIndexWeekAgo is not None:
        _e(site, "trafficIndexWeekAgo", text=str(obs.trafficIndexWeekAgo))


def build_document(observations: Iterable[TrafficObservation], publication_time: str) -> str:
    root = Element(
        f"{{{DATEX2_NS}}}d2LogicalModel",
        {"modelBaseVersion": "3"},
    )

    payload = _e(root, "payloadPublication", attribs={XSI_TYPE: "MeasuredDataPublication", "lang": "en"})
    _e(payload, "publicationTime", text=publication_time)
    pub_creator = _e(payload, "publicationCreator")
    _e(pub_creator, "country", text="pt")
    _e(pub_creator, "nationalIdentifier", text="askem-mimathon-uc4")

    obs_list = list(observations)
    if obs_list:
        first = obs_list[0]
        _e(
            payload,
            "measurementSiteTablePublicationReference",
            id=f"{first.city.countryCode}-{first.city.name}-table",
            version="1.0",
        )

    for i, obs in enumerate(obs_list, start=1):
        _site_measurements(payload, obs, i)

    xml_bytes = tostring(root, encoding="utf-8", xml_declaration=True)
    return minidom.parseString(xml_bytes).toprettyxml(indent="  ")
