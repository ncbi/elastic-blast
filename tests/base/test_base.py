#                           PUBLIC DOMAIN NOTICE
#              National Center for Biotechnology Information
#  
# This software is a "United States Government Work" under the
# terms of the United States Copyright Act.  It was written as part of
# the authors' official duties as United States Government employees and
# thus cannot be copyrighted.  This software is freely available
# to the public for use.  The National Library of Medicine and the U.S.
# Government have not placed any restriction on its use or reproduction.
#   
# Although all reasonable efforts have been taken to ensure the accuracy
# and reliability of the software and data, the NLM and the U.S.
# Government do not and cannot warrant the performance or results that
# may be obtained by using this software or data.  The NLM and the U.S.
# Government disclaim all warranties, express or implied, including
# warranties of performance, merchantability or fitness for any particular
# purpose.
#   
# Please cite NCBI in any work or product based on this material.

"""
Tests for elb/base.py

Author: Greg Boratyn (boratyn@ncbi.nlm.nih.gov)
Created: Fri 12 Feb 2021 01:18:34 AM EDT
"""

from dataclasses import dataclass, field
import configparser
from elastic_blast.base import ConfigParserToDataclassMapper, ParamInfo
from elastic_blast.base import PositiveInteger, Percentage, BoolFromStr, MemoryStr
import pytest


def test_positive_integer():
    """Test PositiveInteger type validation"""
    assert issubclass(type(PositiveInteger(1)), int)
    for val in [1, 2, 5, 100, 2.0, '1', '2', '25']:
        assert PositiveInteger(val) == int(val)
    
    for val in [0, -2, 1.5, '0', '-2', '0.1']:
        with pytest.raises(ValueError):
            PositiveInteger(val)
        

def test_positive_percentage():
    """Test Percentage type validation"""
    assert issubclass(type(Percentage(1)), int)
    for val in [0, 1, 2, 5, 100, 2.0, '1', '2', '25']:
        assert Percentage(val) == int(val)
    
    for val in [-2, 1.5, '-2', '0.1']:
        with pytest.raises(ValueError):
            PositiveInteger(val)


def test_boolfromstr():
    """Test BoolFromStr type"""
    assert BoolFromStr(True)
    assert not BoolFromStr(False)
    for val in ['n', 'N', 'NO', 'No', '0', 'false', 'False', 'FALSE']:
        assert not BoolFromStr(val)

    for val in ['y', 'Y', 'YES', 'Yes', '1', 'true', 'True', 'TRUE']:
        assert BoolFromStr(val)
        

def test_memorystr():
    """Test MemoryStr type validation"""
    for val in ['123G', '123g', '123M', '123m', '123.5m', '25k', '25K']:
        MemoryStr(val)

    for val in [123, '123', '123mm', '123a', 'G']:
        print(val)
        with pytest.raises(ValueError):
            MemoryStr(val)

    assert MemoryStr('1024m').asGB() == 1.0
    assert MemoryStr('3G').asGB() == 3.0
    

def test_configparsertodataclassmapper():
    """Test basic functionality of ConfigParserToDataclassMapper base class"""
    class SomeType:
        def __init__(self, value):
            self.value = int(value) + 1

        def __eq__(self, other):
            return self.value == other.value

    SECTION = 'section'
    EXPECTED_PARAM_1_VALUE = 5
    PARAM_2_ARG = '3'
    EXPECTED_PARAM_2_VALUE = SomeType(PARAM_2_ARG)
    EXPECTED_PARAM_3_VALUE = 0

    @dataclass
    class TestClass(ConfigParserToDataclassMapper):
        param_1: int = EXPECTED_PARAM_1_VALUE  # default value
        param_2: SomeType = field(init=False)  # non-standard type
        param_3: int = field(init=False)       # non default value

        mapping = {'param_1': ParamInfo('Non-existant-section', 'param-name'),
                   'param_2': ParamInfo(SECTION, 'param_2'),
                   'param_3': ParamInfo(SECTION, 'param_3')}
 

    obj = TestClass()
    # uninitialized parameters are set to None
    assert obj.param_2 is None
    # AttributeError mmust be raised on attempt to create a new class attribute
    with pytest.raises(AttributeError):
        obj.attribute_that_does_not_exist = 3
    
    # test for initializing class attribute values from a ConfigParser object
    confpars = configparser.ConfigParser()
    confpars[SECTION] = {'param_2': PARAM_2_ARG,
                         'param_3': str(EXPECTED_PARAM_3_VALUE)}

    obj = TestClass.create_from_cfg(confpars)
    assert isinstance(obj.param_1, int)
    assert obj.param_1 == EXPECTED_PARAM_1_VALUE

    assert isinstance(obj.param_2, SomeType)
    assert obj.param_2 == EXPECTED_PARAM_2_VALUE

    assert isinstance(obj.param_3, int)
    assert obj.param_3 == EXPECTED_PARAM_3_VALUE


def test_bool_param_from_str():
    """Test that boolean config parameters are properly initialized from
    ConfigParser parameters"""

    @dataclass
    class TestConfig(ConfigParserToDataclassMapper):
        param_1: bool
        param_2: bool
        mapping = {'param_1': ParamInfo('section', 'param_1'),
                   'param_2': ParamInfo('section', 'param_2')}

    cfg = configparser.ConfigParser()
    cfg['section'] = {'param_1': 'yes', 'param_2': 'no'}

    conf = TestConfig.create_from_cfg(cfg)
    assert conf.param_1 == True
    assert conf.param_2 == False


def test_configparsertodataclassmapper_missing_mapping():
    """Test that instantiaing a  subclass without mapping attribute raises
    AttributeError"""
    @dataclass
    class TestEmpty(ConfigParserToDataclassMapper):
        pass

    with pytest.raises(AttributeError):
        TestEmpty.create_from_cfg(configparser.ConfigParser())


    @dataclass
    class TestMissing(ConfigParserToDataclassMapper):
        attribute: int = 5

    with pytest.raises(AttributeError):
        TestMissing.create_from_cfg(configparser.ConfigParser())


def test_configparsertodataclassmapper_report_missing_param():
    """Test ConfigParserToDataclassMapper base class for reporting requried
    parameters missing in a ConfigParser object"""
    SECTION = 'section'

    @dataclass
    class TestClass(ConfigParserToDataclassMapper):
        param: int

        mapping = {'param': ParamInfo(SECTION, 'cfg-param')}

    confpars = configparser.ConfigParser()
    confpars[SECTION] = {'other-param': '0'}

    with pytest.raises(ValueError) as err:
        obj = TestClass.create_from_cfg(confpars)
    assert 'Missing' in str(err.value)
    assert 'cfg-param' in str(err.value)
