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
elb/base.py - Definitions of types used by different elb modules

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
Created: Tue 09 Feb 2021 03:52:31 PM EDT
"""

import configparser
import re
from dataclasses import dataclass, field, Field, fields, _MISSING_TYPE
from enum import Enum, auto
from typing import Dict, List, Union, Optional, NamedTuple

@dataclass(frozen=True)
class InstanceProperties:
    """Properties of a cloud instance

    Attributes:
        ncpus: Number of vCPUs
        memory: Available RAM
    """
    ncpus : int
    memory : float


@dataclass(frozen=True)
class QuerySplittingResults:
    """ Results from query splitting operation """
    query_length : int
    query_batches : List[str]

    def num_batches(self) -> int:
        return len(self.query_batches)


class PositiveInteger(int):
    """A subclass of int that only accepts positive integers. The value is
    validated before object creation"""
    # a bug in mypy does not allow for type annotation here:
    # https://github.com/python/mypy/issues/6061
    def __new__(cls, value):
        """Constructor, validates that argumant is a positive integer after
        conversion to int"""
        try:
            if isinstance(value, float) and value != round(value):
                raise ValueError
            int_value = int(value)
            if int_value <= 0:
                raise ValueError()
        except ValueError as err:
            msg = 'Must be a positive integer.'
            raise ValueError(msg)
        return super(cls, cls).__new__(cls, value)


class Percentage(int):
    """A subclass of int that accepts only percentages: an integer between 0
    and 100"""
    def __new__(cls, value):
        try:
            if isinstance(value, float) and value != round(value):
                raise ValueError
            int_value = int(value)
            if int_value < 0 or int_value > 100:
                raise ValueError
        except ValueError:
            msg = 'Percentage must be a positive integer between 0 and 100'
            raise ValueError(msg)
        return super(cls, cls).__new__(cls, value)


class BoolFromStr:
    """A class that converts strings to boolean values.
    False is created if string value is one of: n, no, 0, false, or empty
    string. True is created otherwise. String values are not case sensitive."""
    def __new__(cls, value):
        if isinstance(value, str):
            return not value.lower() in ['n', 'no', '0', 'false', '']
        return bool(value)


class MemoryStr(str):
    """A subclass of str that only accepts properly formated memory amounts as
    a number followed by a single chanracter for a unit. The value is
    validated before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        str_value = str(value)
        number_re = re.compile(r'^\d+[kKmMgGtT]$|^\d+.\d+[kKmMgGtT]$')
        if not number_re.match(str_value):
            raise ValueError('Memory request or limit must be specified by a number followed by a unit, for example 100m')
        if float(str_value[:-1]) <= 0:
            raise ValueError('Memory request or limit must be larger than zero')
        return super(cls, cls).__new__(cls, str_value)


    def asGB(self) -> float:
        """Return the amount of memory in GB as float"""
        mult = 1.0
        if self[-1].upper() == 'K':
            mult /= 1024 ** 2
        elif self[-1].upper() == 'M':
            mult /= 1024
        elif self[-1].upper() == 'T':
            mult *= 1024
        return float(self[:-1]) * mult

    def asMB(self) -> float:
        """Return the amount of memory in MB as float"""
        mult = 1.0
        if self[-1].upper() == 'K':
            mult /= 1024
        elif self[-1].upper() == 'G':
            mult *= 1024
        elif self[-1].upper() == 'T':
            mult *= 1024 ** 2
        return float(self[:-1]) * mult


class DBSource(Enum):
    """Sources of a BLAST database supported by update_blastdb.pl from BLAST+ package"""
    GCP = auto()
    AWS = auto()
    NCBI = auto()
    def __repr__(self):
        return f"'{self.name}'"


class ParamInfo(NamedTuple):
    """Data structure used to link config parameters with ConfigParser
    parameter names:
        section: ConfigParser section name
        param_name: ConfigParser parameter name"""
    #FIXME: add environment and command line parameter names
    section: str
    param_name: str


@dataclass
class ConfigParserToDataclassMapper:
    """Base class that provides methods for dataclasses with elements linked
    to ConfigParser parameter names. A child class must be a dataclass.

    Attributes:
        mapping: A dictionary with a map (class attribute, ConfigParser
        parameter or None)
    """
    
    mapping: Dict[str, Optional[ParamInfo]] = field(init=False)

    def __init__(self):
        """Contructor needed so that dataclass does not auto generate one"""
        pass


    @classmethod
    def create_from_cfg(cls, parser, **kwargs):
        """Meant to be used by a subclass. Create a subclass object
        initializing attribute values from ConfigParser object using mapping
        in the mapped dictonary.

        Arguments:
            parser: A ConfigParser object
            kwargs: Other parameters required by sublcass constructor

        Raises:
            ValueError: if a required parameter is missing in ConfigParser or
            ValueError is raised during subclass attribute initialization
        """
        # check that all dataclass attributes are mapped to configparser params
        cls.validate_mapping()
        errors = []
        for field in fields(cls):
            if field.init:
                mapped = cls.mapping[field.name]
                # ignore dataclass attributes mapped to None
                if mapped is None:
                    continue
                # skip dataclass attributes that with default values and no
                # parameter values in ConfigParser object
                # field.default == dataclass._MISSING_TYPE means that the
                # dataclass attribute has no default value
                if not isinstance(field.default, _MISSING_TYPE) and \
                       (mapped.section not in parser or \
                        mapped.param_name not in parser[mapped.section]):
                    continue

                # report a required parameter missing in ConfigParser
                if isinstance(field.default, _MISSING_TYPE) and \
                       (mapped.section not in parser or \
                        mapped.param_name not in parser[mapped.section]):
                    errors.append(f'Missing {mapped.param_name}')
                    continue

                # initialize dataclass attribute value, call the appropriate
                # class constructor
                kwargs[field.name] = cls.initialize_value(field, mapped,
                                                          parser, errors)

        # report attribute initialization errors
        if errors:
            # if errors were reported for required parameters, test optional
            # parameters and add include error messages before raising
            # exception
            cls._test_optional_cfg_params(parser, errors)
            raise ValueError('\n'.join(errors))

        # call subclass constructor
        obj = cls(**kwargs)
        # initialize parameters not settable via class constructor
        obj._init_optional_from_cfg(parser, errors)
        if errors:
            raise ValueError('\n'.join(errors))
        return obj

    
    @classmethod
    def validate_mapping(cls):
        """Verify that all class attributes appear in the mapping dictionary.
        Raises AttributeError if an attribute is not in mapping."""
        for field in fields(cls):
            if field.name not in cls.mapping and field.name != 'mapping':
                raise AttributeError(f'Field {field.name} does not have mapping to ConfigParser params')


    def _init_optional_from_cfg(self, parser: configparser.ConfigParser,
                                errors: List[str]):
        """Initialize from ConfigParser only class attributes that are not
        parameters of class constructor.

        Parameters:
            parser: ConfigParser object
            errors: A list where error messages will be appended
        """
        self.validate_mapping()
        for field in fields(self):
            # skip attrubutes initialized via class constructor and those that
            # map to None
            if field.name == 'mapping' or field.init or self.mapping[field.name] is None:
                continue
            mapped = self.mapping[field.name]
            if mapped is None:
                continue
            if mapped.section in parser and mapped.param_name in parser[mapped.section]:
                param = self.initialize_value(field, mapped, parser, errors)
                self.__setattr__(field.name, param)


    @classmethod
    def _test_optional_cfg_params(cls, parser: configparser.ConfigParser,
                                  errors: List[str]):
        """Try initializing from ConfigParser only class attributes that are
        not parameters of class constructor to report any inavlid values

        Parameters:
            parser: ConfigParser object
            errors: A list where error messages will be appended
        """
        cls.validate_mapping()
        for field in fields(cls):
            # skip attrubutes initialized via class constructor and those that
            # map to None
            if field.name == 'mapping' or field.init or cls.mapping[field.name] is None:
                continue
            mapped = cls.mapping[field.name]
            if mapped is None:
                continue
            if mapped.section in parser and mapped.param_name in parser[mapped.section]:
                cls.initialize_value(field, mapped, parser, errors)


    @staticmethod
    def get_non_union_type(field: Field):
        """For a dataclass field, if the type is a Union, return the first type
        that is not None. Otherwise return field's type.

        Arguments:
            field: Dataclass field

        Returns:
            If fieds.type is a Union, then the first type that is not None,
            otherwise field.type"""
        ftype = field.type
        # FIXME: in python3.8 this can be done via typing.get_origin()
        if getattr(ftype, '__origin__', None) is not None and \
               ftype.__origin__ == Union:
            ftype = [t for t in ftype.__args__ if t != type(None)][0]
        return ftype


    @classmethod
    def initialize_value(cls, field, mapped, parser, errors):
        """Helper function to initialize a single attribute from a
        ConfigParser object parameter value.

        Attributes:
            field: dataclass field object
            mapped: ParamInfo object
            parser: ConfigParser object
            errors: Error messages will be added to thie list
        """
        # dataclass attribute type
        # Union types cannot be initialized, types like Optional[int] are
        # really Union[int, None]. If the attribute type is a Union,
        # initialize the first type that is not None.
        ftype = cls.get_non_union_type(field)

        # if attribute type is an enum, initialize it from str
        if issubclass(ftype, Enum):
            try:
                # first try the string as is
                value = ftype[parser[mapped.section][mapped.param_name]]
            except KeyError:
                # then try uppercase
                try:
                    value = ftype[parser[mapped.section][mapped.param_name].upper()]
                except KeyError:
                    errors.append(f'Parameter "{mapped.param_name}" has invalid value: "{parser[mapped.section][mapped.param_name]}", should be one of {", ".join([i.name for i in ftype])}')
                    # in case of an error initialize the attribute to any value
                    # so that something can be returned and problems with
                    # more parameters can be reported from a single run
                    value = [i for i in ftype][0]

        # for boolean attributes, use ConfigParser converter from str
        elif ftype == bool:
            value = parser.getboolean(mapped.section, mapped.param_name)

        # otherwise call attribute's class constructor with ConfigParser
        # parameter value
        else:
            try:
                value = ftype(parser[mapped.section][mapped.param_name])
            except ValueError as err:
                errors.append(f'Parameter "{mapped.param_name}" has an invalid value: "{parser[mapped.section][mapped.param_name]}": {str(err)}')
                if '$' in parser[mapped.section][mapped.param_name]:
                    errors.append('The character $ is not allowed, as ElasticBLAST configuration files do not support variable substitution.')
                value = None
        return value


    def re_initialize_values(self):
        """Reinitialize all dataclass attributes to have them in the appropriate
        type. Useful if an object was initialized with values of only basic types,
        for example in deserializaton."""
        for field in fields(self):
            if field.name == 'mapping':
                continue
            # If this function is called from self.__post_init__, not all
            # attributes will be initialized yet. Skip those.
            try:
                value = self.__getattribute__(field.name)
            except AttributeError:
                continue
            if value is None:
                continue
            ftype = self.get_non_union_type(field)
            if ftype != type(self.__getattribute__(field.name)):
                self.__setattr__(field.name, ftype(value))


    # FIXME: this function does not really belong in this class and should
    # be part of another class or a class decorator
    def __setattr__(self, name, value):
        """Prevent creation of new attributes to catch misspelled class
        attribute values. Raises AttributeError if a value is being assigned to
        a new class attribute."""
        if name not in [i.name for i in fields(self)]:
            raise AttributeError(f'Attribute {name} does not exist in class {type(self)}')
        super().__setattr__(name, value)


    def __getattr__(self, name):
        """Return None for uninitialized dataclass attributes.
        Raises AttrubuteError for other non-existant class attributes"""
        if name in [i.name for i in fields(self)]:
            return None
        else:
            raise AttributeError(f'"{type(self).__name__}" has no attribute "{name}"')
